#!/usr/bin/env python3
"""
Recipe Search Lambda - brute-force similarity search over recipes in S3

No dedicated search index: every recipe JSON in S3 already carries its own
Bedrock embedding (written by vision-processor), so a search just loads all
of them and scores them in memory. Fine for the small recipe counts this
project runs at; if the catalog grows into the thousands, revisit.
"""

import os
import re
import json
import math
import time
import boto3
from concurrent.futures import ThreadPoolExecutor

# Setup
s3 = boto3.client('s3')
bedrock = boto3.client('bedrock-runtime', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
dynamodb = boto3.client('dynamodb')

# Configuration
S3_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME')
DYNAMODB_TABLE_NAME = os.environ.get('DYNAMODB_TABLE_NAME')
RECIPES_PREFIX = 'recipes/json/'


def is_authorized(event):
    """Check the Authorization header against a login-issued token in DynamoDB"""
    headers = event.get('headers') or {}
    auth_header = headers.get('authorization') or headers.get('Authorization') or ''
    token = auth_header[7:] if auth_header.lower().startswith('bearer ') else auth_header

    if not token or not DYNAMODB_TABLE_NAME:
        return False

    try:
        response = dynamodb.get_item(
            TableName=DYNAMODB_TABLE_NAME,
            Key={'metric_type': {'S': 'auth_token'}, 'metric_id': {'S': token}}
        )
        item = response.get('Item')
        if not item:
            return False
        ttl = int(item.get('ttl', {}).get('N', '0'))
        return ttl > int(time.time())
    except Exception as e:
        print(f"Auth check failed: {e}")
        return False


def unauthorized_response():
    return {
        'statusCode': 401,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps({'error': 'Unauthorized'})
    }

# (field, weight) pairs used for keyword scoring
KEYWORD_TEXT_FIELDS = [
    ('title', 3), ('title_en', 3),
    ('description', 2), ('description_en', 2),
    ('semantic_text', 1),
]
RRF_K = 60  # reciprocal rank fusion constant, matches prior OpenSearch fallback


def handler(event, context):
    """
    Handle recipe search requests

    Query parameters:
    - q: search query (required)
    - mode: 'semantic' (vector only), 'keyword' (text only), 'hybrid' (both, default)
    - limit: number of results (default: 5, max: 20)
    """
    try:
        if not is_authorized(event):
            return unauthorized_response()

        params = event.get('queryStringParameters', {}) or {}
        query = params.get('q', '').strip()
        mode = params.get('mode', 'hybrid').lower()
        limit = min(int(params.get('limit', 5)), 20)

        if not query:
            return _response(400, {'error': 'Query parameter "q" is required'})

        print(f"Search query: '{query}', mode: {mode}, limit: {limit}")

        recipes = load_all_recipes()
        print(f"Loaded {len(recipes)} recipes from S3")

        query_embedding = None
        if mode in ('semantic', 'hybrid'):
            query_embedding = generate_query_embedding(query)

        ranked = score_recipes(recipes, query, query_embedding, mode)
        top = ranked[:limit]

        for recipe in top:
            recipe.pop('semantic_embedding', None)
            recipe['search_mode'] = mode

        return _response(200, {
            'query': query,
            'mode': mode,
            'total': len(top),
            'recipes': top
        })

    except Exception as e:
        print(f"Search error: {str(e)}")
        import traceback
        traceback.print_exc()
        return _response(500, {'error': str(e)})


def _response(status_code, body):
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps(body, ensure_ascii=False)
    }


def load_all_recipes():
    """List and fetch every recipe JSON under recipes/json/, in parallel"""
    keys = []
    paginator = s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=RECIPES_PREFIX):
        for obj in page.get('Contents', []):
            if obj['Key'].endswith('.json'):
                keys.append(obj['Key'])

    if not keys:
        return []

    def fetch(key):
        try:
            response = s3.get_object(Bucket=S3_BUCKET_NAME, Key=key)
            recipe = json.loads(response['Body'].read().decode('utf-8'))
            recipe['recipe_id'] = key.rsplit('/', 1)[-1].replace('.json', '')
            return recipe
        except Exception as e:
            print(f"Failed to load {key}: {e}")
            return None

    with ThreadPoolExecutor(max_workers=min(16, len(keys))) as pool:
        results = list(pool.map(fetch, keys))

    return [r for r in results if r is not None]


def generate_query_embedding(query):
    """Generate embedding for search query using Bedrock Titan"""
    response = bedrock.invoke_model(
        modelId='amazon.titan-embed-text-v2:0',
        body=json.dumps({
            "inputText": query,
            "dimensions": 1024,
            "normalize": True
        })
    )
    response_body = json.loads(response['body'].read())
    return response_body['embedding']


def cosine_similarity(a, b):
    """Plain-Python cosine similarity; fine at this scale, no numpy needed"""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def keyword_score(query, recipe):
    """Weighted substring match across the same fields OpenSearch used to boost"""
    terms = [t for t in re.split(r'\s+', query.lower()) if t]
    if not terms:
        return 0.0

    weighted_texts = []
    for field, weight in KEYWORD_TEXT_FIELDS:
        weighted_texts.append((str(recipe.get(field) or '').lower(), weight))

    for field in ('ingredients', 'seasonings'):
        for item in recipe.get(field, []) or []:
            if isinstance(item, dict):
                name = f"{item.get('name', '')} {item.get('name_en', '')}"
            else:
                name = str(item)
            weighted_texts.append((name.lower(), 1))

    for field in ('category', 'category_en'):
        weighted_texts.append((' '.join(recipe.get(field, []) or []).lower(), 1))

    health = recipe.get('health', {}) or {}
    for field in ('health_tags', 'health_tags_en'):
        weighted_texts.append((' '.join(health.get(field, []) or []).lower(), 1))

    score = 0.0
    for term in terms:
        for text, weight in weighted_texts:
            if term in text:
                score += weight

    return score / len(terms)


def score_recipes(recipes, query, query_embedding, mode):
    """
    Score and sort recipes for the given mode.

    'hybrid' combines keyword and semantic results with reciprocal rank
    fusion (same RRF approach the old OpenSearch fallback used) instead of
    averaging raw scores, since keyword_score and cosine_similarity live on
    different scales.
    """
    for recipe in recipes:
        recipe['_keyword_score'] = keyword_score(query, recipe) if mode in ('keyword', 'hybrid') else 0.0
        recipe['_semantic_score'] = cosine_similarity(query_embedding, recipe.get('semantic_embedding')) \
            if mode in ('semantic', 'hybrid') else 0.0

    if mode == 'keyword':
        for recipe in recipes:
            recipe['search_score'] = recipe['_keyword_score']
    elif mode == 'semantic':
        for recipe in recipes:
            recipe['search_score'] = recipe['_semantic_score']
    else:  # hybrid
        keyword_rank = {
            r['recipe_id']: rank for rank, r in
            enumerate(sorted(recipes, key=lambda r: r['_keyword_score'], reverse=True), 1)
        }
        semantic_rank = {
            r['recipe_id']: rank for rank, r in
            enumerate(sorted(recipes, key=lambda r: r['_semantic_score'], reverse=True), 1)
        }
        for recipe in recipes:
            rid = recipe['recipe_id']
            recipe['search_score'] = (
                1.0 / (keyword_rank[rid] + RRF_K) + 1.0 / (semantic_rank[rid] + RRF_K)
            )

    for recipe in recipes:
        recipe.pop('_keyword_score', None)
        recipe.pop('_semantic_score', None)

    recipes.sort(key=lambda r: r['search_score'], reverse=True)
    return recipes
