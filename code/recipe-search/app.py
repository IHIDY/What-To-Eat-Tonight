#!/usr/bin/env python3
"""
Recipe Search Lambda - Hybrid search with vector similarity and keyword matching
"""

import os
import json
import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

# Setup
s3 = boto3.client('s3')
bedrock = boto3.client('bedrock-runtime', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Configuration
OPENSEARCH_ENDPOINT = os.environ.get('OPENSEARCH_ENDPOINT')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
S3_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME')
OPENSEARCH_INDEX = 'recipes'

# Initialize OpenSearch client
_opensearch_client = None

def get_opensearch_client():
    """Create OpenSearch client with AWS4Auth (lazy initialization)"""
    global _opensearch_client

    if _opensearch_client is None:
        session = boto3.Session()
        credentials = session.get_credentials()
        awsauth = AWS4Auth(
            credentials.access_key,
            credentials.secret_key,
            AWS_REGION,
            'es',
            session_token=credentials.token
        )

        _opensearch_client = OpenSearch(
            hosts=[{'host': OPENSEARCH_ENDPOINT, 'port': 443}],
            http_auth=awsauth,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection
        )

    return _opensearch_client


def handler(event, context):
    """
    Handle recipe search requests

    Query parameters:
    - q: search query (required)
    - mode: 'semantic' (vector only), 'keyword' (text only), 'hybrid' (both, default)
    - limit: number of results (default: 5, max: 20)
    """
    try:
        # Parse query parameters
        params = event.get('queryStringParameters', {}) or {}
        query = params.get('q', '').strip()
        mode = params.get('mode', 'hybrid').lower()
        limit = min(int(params.get('limit', 5)), 20)

        if not query:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'Query parameter "q" is required'})
            }

        print(f"Search query: '{query}', mode: {mode}, limit: {limit}")

        # Perform search based on mode
        if mode == 'semantic':
            results = semantic_search(query, limit)
        elif mode == 'keyword':
            results = keyword_search(query, limit)
        else:  # hybrid
            results = hybrid_search(query, limit)

        # Fetch full recipe JSONs from S3
        recipes = []
        for result in results:
            recipe_id = result['recipe_id']
            score = result['score']

            try:
                # Read full JSON from S3
                json_key = f"recipes/json/{recipe_id}.json"
                response = s3.get_object(Bucket=S3_BUCKET_NAME, Key=json_key)
                recipe_json = json.loads(response['Body'].read().decode('utf-8'))

                # Add metadata
                recipe_json['search_score'] = score
                recipe_json['search_mode'] = mode
                recipes.append(recipe_json)

            except s3.exceptions.NoSuchKey:
                print(f"Warning: Recipe JSON not found: {json_key}")
                continue
            except Exception as e:
                print(f"Error fetching recipe {recipe_id}: {str(e)}")
                continue

        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'query': query,
                'mode': mode,
                'total': len(recipes),
                'recipes': recipes
            }, ensure_ascii=False)
        }

    except Exception as e:
        print(f"Search error: {str(e)}")
        import traceback
        traceback.print_exc()

        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': str(e)})
        }


def generate_query_embedding(query):
    """Generate embedding for search query using Bedrock"""
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


def semantic_search(query, limit):
    """Vector similarity search using k-NN"""
    print("Performing semantic search...")

    # Generate query embedding
    query_embedding = generate_query_embedding(query)

    # k-NN search
    os_client = get_opensearch_client()
    search_body = {
        "size": limit,
        "_source": ["recipe_id", "title", "title_en", "semantic_text"],
        "query": {
            "knn": {
                "semantic_embedding": {
                    "vector": query_embedding,
                    "k": limit
                }
            }
        }
    }

    response = os_client.search(index=OPENSEARCH_INDEX, body=search_body)

    results = []
    for hit in response['hits']['hits']:
        results.append({
            'recipe_id': hit['_source']['recipe_id'],
            'score': hit['_score'],
            'title': hit['_source'].get('title'),
            'title_en': hit['_source'].get('title_en')
        })

    print(f"Found {len(results)} results")
    return results


def keyword_search(query, limit):
    """Text-based keyword search"""
    print("Performing keyword search...")

    os_client = get_opensearch_client()
    search_body = {
        "size": limit,
        "_source": ["recipe_id", "title", "title_en", "semantic_text"],
        "query": {
            "multi_match": {
                "query": query,
                "fields": [
                    "title^3",           # Boost title matches
                    "title_en^3",
                    "description^2",
                    "description_en^2",
                    "semantic_text",
                    "ingredients",
                    "seasonings",
                    "category",
                    "category_en",
                    "health_tags",
                    "health_tags_en"
                ],
                "type": "best_fields",
                "fuzziness": "AUTO"   # Handle typos
            }
        }
    }

    response = os_client.search(index=OPENSEARCH_INDEX, body=search_body)

    results = []
    for hit in response['hits']['hits']:
        results.append({
            'recipe_id': hit['_source']['recipe_id'],
            'score': hit['_score'],
            'title': hit['_source'].get('title'),
            'title_en': hit['_source'].get('title_en')
        })

    print(f"Found {len(results)} results")
    return results


def hybrid_search(query, limit):
    """
    Hybrid search combining semantic and keyword search
    Uses RRF (Reciprocal Rank Fusion) for combining results
    """
    print("Performing hybrid search...")

    # Generate query embedding
    query_embedding = generate_query_embedding(query)

    os_client = get_opensearch_client()
    search_body = {
        "size": limit,
        "_source": ["recipe_id", "title", "title_en", "semantic_text"],
        "query": {
            "hybrid": {
                "queries": [
                    # Semantic search (k-NN)
                    {
                        "knn": {
                            "semantic_embedding": {
                                "vector": query_embedding,
                                "k": limit * 2  # Get more candidates
                            }
                        }
                    },
                    # Keyword search
                    {
                        "multi_match": {
                            "query": query,
                            "fields": [
                                "title^3",
                                "title_en^3",
                                "description^2",
                                "description_en^2",
                                "semantic_text",
                                "ingredients",
                                "seasonings",
                                "category",
                                "category_en"
                            ],
                            "type": "best_fields",
                            "fuzziness": "AUTO"
                        }
                    }
                ]
            }
        }
    }

    try:
        response = os_client.search(index=OPENSEARCH_INDEX, body=search_body)

        results = []
        for hit in response['hits']['hits']:
            results.append({
                'recipe_id': hit['_source']['recipe_id'],
                'score': hit['_score'],
                'title': hit['_source'].get('title'),
                'title_en': hit['_source'].get('title_en')
            })

        print(f"Hybrid search found {len(results)} results")
        return results

    except Exception as e:
        # Fallback: If hybrid query is not supported, combine results manually
        print(f"Hybrid query not supported, using fallback: {str(e)}")
        return hybrid_search_fallback(query, limit)


def hybrid_search_fallback(query, limit):
    """
    Fallback hybrid search: run semantic and keyword separately, then merge
    """
    # Get results from both methods
    semantic_results = semantic_search(query, limit)
    keyword_results = keyword_search(query, limit)

    # Combine using RRF (Reciprocal Rank Fusion)
    recipe_scores = {}

    # Add semantic results (rank-based scoring)
    for rank, result in enumerate(semantic_results, 1):
        recipe_id = result['recipe_id']
        recipe_scores[recipe_id] = recipe_scores.get(recipe_id, 0) + 1.0 / (rank + 60)

    # Add keyword results
    for rank, result in enumerate(keyword_results, 1):
        recipe_id = result['recipe_id']
        recipe_scores[recipe_id] = recipe_scores.get(recipe_id, 0) + 1.0 / (rank + 60)

    # Sort by combined score
    sorted_recipes = sorted(recipe_scores.items(), key=lambda x: x[1], reverse=True)

    # Build result list
    results = []
    recipe_map = {r['recipe_id']: r for r in semantic_results + keyword_results}

    for recipe_id, score in sorted_recipes[:limit]:
        if recipe_id in recipe_map:
            result = recipe_map[recipe_id]
            result['score'] = score
            results.append(result)

    print(f"Fallback hybrid search found {len(results)} results")
    return results