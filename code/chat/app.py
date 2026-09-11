#!/usr/bin/env python3
"""
Chat Lambda - AI-powered recipe assistant with search capability
Uses Gemini function calling to search recipes and provide recommendations
"""

import os
import re
import json
import math
import time
import boto3
from datetime import datetime
from decimal import Decimal
from google import genai
from concurrent.futures import ThreadPoolExecutor

# Setup
client = genai.Client(api_key=os.environ.get('GEMINI_API_KEY'))
bedrock = boto3.client('bedrock-runtime', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
s3 = boto3.client('s3')
dynamodb = boto3.client('dynamodb')

# Configuration
S3_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME')
DYNAMODB_TABLE_NAME = os.environ.get('DYNAMODB_TABLE_NAME')
RECIPES_PREFIX = 'recipes/json/'
CHAT_MODEL = 'gemini-3.6-flash'
# Rough blended estimate for cost tracking, same "good enough" approach the
# old OpenAI code used - check current Gemini pricing if this needs to be exact
GEMINI_PRICE_PER_MILLION_TOKENS = 0.50

# (field, weight) pairs used for keyword scoring
KEYWORD_TEXT_FIELDS = [
    ('title', 3), ('title_en', 3),
    ('description', 2), ('description_en', 2),
    ('semantic_text', 1),
]
RRF_K = 60  # reciprocal rank fusion constant, matches recipe-search Lambda


def record_stat(metric_type, metric_id, increment=1, extra_attributes=None):
    """
    Record statistics to DynamoDB

    Args:
        metric_type: Type of metric (e.g., 'api_call', 'gemini_api_call', 'recipe_view')
        metric_id: ID of the metric (e.g., 'POST_/chat', 'gemini-3.6-flash', recipe_id)
        increment: Value to increment count by (default: 1)
        extra_attributes: Dictionary of additional attributes to update (e.g., total_tokens, total_cost)
    """
    if not DYNAMODB_TABLE_NAME:
        return  # Skip if DynamoDB is not configured

    try:
        # Build update expression
        update_parts = ['#count :inc']
        attr_names = {'#count': 'count'}
        attr_values = {':inc': {'N': str(increment)}, ':time': {'S': datetime.utcnow().isoformat()}}

        # Add extra attributes if provided
        set_parts = []
        if extra_attributes:
            for key, value in extra_attributes.items():
                attr_name_placeholder = f'#{key}'
                attr_value_placeholder = f':{key}'
                attr_names[attr_name_placeholder] = key
                set_parts.append(f'{attr_name_placeholder} = {attr_value_placeholder}')

                # Handle different value types
                if isinstance(value, (int, float)):
                    attr_values[attr_value_placeholder] = {'N': str(value)}
                elif isinstance(value, Decimal):
                    attr_values[attr_value_placeholder] = {'N': str(value)}
                else:
                    attr_values[attr_value_placeholder] = {'S': str(value)}

        # Add last_updated to SET parts
        set_parts.append('last_updated = :time')

        # Build final update expression
        update_expression = f'ADD {update_parts[0]} SET {", ".join(set_parts)}'

        dynamodb.update_item(
            TableName=DYNAMODB_TABLE_NAME,
            Key={
                'metric_type': {'S': metric_type},
                'metric_id': {'S': metric_id}
            },
            UpdateExpression=update_expression,
            ExpressionAttributeNames=attr_names if len(attr_names) > 0 else None,
            ExpressionAttributeValues=attr_values
        )
        print(f"Recorded stat: {metric_type}/{metric_id} +{increment}")
    except Exception as e:
        # Don't fail the main request if stats recording fails
        print(f"Failed to record stat: {e}")


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
    """Score and sort recipes; 'hybrid' fuses keyword/semantic rankings via RRF"""
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


def search_recipes(query, mode='hybrid', limit=5):
    """
    Search recipes by brute-force scoring every recipe JSON in S3

    Args:
        query: Search query string
        mode: Search mode ('semantic', 'keyword', 'hybrid')
        limit: Number of results to return

    Returns:
        List of recipe objects with full details
    """
    print(f"Searching recipes: query='{query}', mode={mode}, limit={limit}")

    try:
        recipes = load_all_recipes()
        print(f"Loaded {len(recipes)} recipes")

        query_embedding = None
        if mode in ('semantic', 'hybrid'):
            response = bedrock.invoke_model(
                modelId='amazon.titan-embed-text-v2:0',
                body=json.dumps({
                    "inputText": query,
                    "dimensions": 1024,
                    "normalize": True
                })
            )
            response_body = json.loads(response['body'].read())
            query_embedding = response_body['embedding']
            record_stat('bedrock_api_call', 'amazon.titan-embed-text-v2:0')

        ranked = score_recipes(recipes, query, query_embedding, mode)
        top = ranked[:limit]

        for recipe in top:
            recipe.pop('semantic_embedding', None)
            record_stat('recipe_view', recipe['recipe_id'])

        print(f"Found {len(top)} recipes")
        return top

    except Exception as e:
        print(f"Search error: {e}")
        import traceback
        traceback.print_exc()
        return []


SEARCH_RECIPES_TOOL = {
    "type": "function",
    "name": "search_recipes",
    "description": "Search for recipes in the database. Use this when the user asks about finding recipes, looking for dishes, or wants recommendations based on ingredients, cuisine type, difficulty, or health considerations.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query. Can be ingredients (e.g., 'pork ribs'), dish name (e.g., 'steamed dishes'), cuisine type (e.g., 'Cantonese'), or health requirements (e.g., 'low sodium')."
            },
            "mode": {
                "type": "string",
                "enum": ["semantic", "keyword", "hybrid"],
                "description": "Search mode. Use 'semantic' for concept-based search, 'keyword' for exact matches, 'hybrid' for best results (default)."
            },
            "limit": {
                "type": "integer",
                "description": "Number of recipes to return (default: 5, max: 10)"
            }
        },
        "required": ["query"]
    }
}

SYSTEM_INSTRUCTION = """You are a helpful recipe assistant. You help users find recipes and provide cooking advice.

When users ask about recipes, use the search_recipes function to find relevant recipes from the database.

After searching, provide:
1. A brief introduction
2. List of recommended recipes with key details (title, difficulty, servings, key ingredients)
3. Brief explanation of why each recipe fits their request
4. Any relevant cooking tips or health considerations

Be conversational and friendly. Support both Chinese and English. Use emojis occasionally to make it engaging."""


def handler(event, context):
    """
    Lambda handler for chat endpoint

    Accepts POST requests with:
    {
        "message": "User's question about recipes",
        "interaction_id": "..."  // Optional, from the previous response - continues that conversation
    }
    """
    try:
        if not is_authorized(event):
            return unauthorized_response()

        # Parse request
        body = json.loads(event.get('body', '{}'))
        user_message = body.get('message', '').strip()
        interaction_id = body.get('interaction_id')

        if not user_message:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'Message is required'})
            }

        print(f"User message: {user_message}")

        # Record API call
        record_stat('api_call', 'POST_/chat')

        # Gemini's Interactions API keeps conversation state server-side;
        # each call only needs the new input plus the previous interaction's id
        current_input = user_message

        max_iterations = 3
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            print(f"Gemini iteration {iteration}")

            interaction = client.interactions.create(
                model=CHAT_MODEL,
                input=current_input,
                tools=[SEARCH_RECIPES_TOOL],
                system_instruction=SYSTEM_INSTRUCTION,
                previous_interaction_id=interaction_id
            )
            interaction_id = interaction.id

            # Record Gemini API call statistics (best-effort; don't let this break chat)
            try:
                tokens_used = interaction.usage.total_tokens
                estimated_cost = Decimal(str(tokens_used * GEMINI_PRICE_PER_MILLION_TOKENS / 1_000_000))
                record_stat(
                    'gemini_api_call',
                    CHAT_MODEL,
                    extra_attributes={
                        'total_tokens': tokens_used,
                        'total_cost': estimated_cost
                    }
                )
            except Exception as e:
                print(f"Could not record token usage: {e}")

            function_call_steps = [s for s in (interaction.steps or []) if s.type == 'function_call']

            if function_call_steps:
                # Execute tool calls
                result_input = []
                for step in function_call_steps:
                    function_name = step.name
                    function_args = step.arguments or {}

                    print(f"Executing function: {function_name} with args: {function_args}")

                    if function_name == 'search_recipes':
                        recipes = search_recipes(
                            query=function_args.get('query'),
                            mode=function_args.get('mode', 'hybrid'),
                            limit=function_args.get('limit', 5)
                        )

                        result_input.append({
                            "type": "function_result",
                            "name": function_name,
                            "call_id": step.id,
                            "result": json.dumps({"recipes": recipes}, ensure_ascii=False)
                        })

                # Feed the function results back in and continue the loop
                current_input = result_input
                continue

            else:
                # No tool calls, return the final response
                return {
                    'statusCode': 200,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'response': interaction.output_text,
                        'interaction_id': interaction_id
                    }, ensure_ascii=False)
                }

        # Max iterations reached
        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': 'Max iterations reached'})
        }

    except Exception as e:
        print(f"Chat error: {str(e)}")
        import traceback
        traceback.print_exc()

        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': str(e)})
        }
