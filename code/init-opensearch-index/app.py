#!/usr/bin/env python3
"""
Lambda function to initialize OpenSearch index with k-NN mapping
"""

import os
import json
import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

# Configuration from environment
OPENSEARCH_ENDPOINT = os.environ.get('OPENSEARCH_ENDPOINT')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
INDEX_NAME = 'recipes'

def get_opensearch_client():
    """Create OpenSearch client with AWS4Auth"""
    session = boto3.Session()
    credentials = session.get_credentials()

    awsauth = AWS4Auth(
        credentials.access_key,
        credentials.secret_key,
        AWS_REGION,
        'es',
        session_token=credentials.token
    )

    client = OpenSearch(
        hosts=[{'host': OPENSEARCH_ENDPOINT, 'port': 443}],
        http_auth=awsauth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection
    )

    return client

def handler(event, context):
    """Lambda handler to create OpenSearch index"""

    try:
        client = get_opensearch_client()

        # Check for action parameter
        action = event.get('action', 'create')
        force = event.get('force', False)

        # Check if index exists
        index_exists = client.indices.exists(index=INDEX_NAME)

        if action == 'delete' and index_exists:
            client.indices.delete(index=INDEX_NAME)
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': f'Index {INDEX_NAME} deleted successfully'
                })
            }

        if index_exists and not force:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'message': f'Index {INDEX_NAME} already exists. Use force=true to recreate.'
                })
            }

        if index_exists and force:
            client.indices.delete(index=INDEX_NAME)
            print(f"Deleted existing index: {INDEX_NAME}")

        # Index settings and mappings
        index_body = {
            "settings": {
                "index": {
                    "knn": True,  # Enable k-NN plugin
                    "knn.algo_param.ef_search": 100,
                    "number_of_shards": 1,
                    "number_of_replicas": 0
                }
            },
            "mappings": {
                "properties": {
                    "recipe_id": {"type": "keyword"},

                    # Chinese fields
                    "title": {
                        "type": "text",
                        "analyzer": "ik_max_word",
                        "search_analyzer": "ik_smart"
                    },
                    "description": {
                        "type": "text",
                        "analyzer": "ik_max_word",
                        "search_analyzer": "ik_smart"
                    },

                    # English fields
                    "title_en": {"type": "text", "analyzer": "english"},
                    "description_en": {"type": "text", "analyzer": "english"},

                    # Arrays
                    "ingredients": {"type": "keyword"},
                    "seasonings": {"type": "keyword"},
                    "category": {"type": "keyword"},
                    "category_en": {"type": "keyword"},
                    "health_tags": {"type": "keyword"},
                    "health_tags_en": {"type": "keyword"},

                    # Metadata
                    "difficulty": {"type": "keyword"},
                    "servings": {"type": "integer"},

                    # Semantic search
                    "semantic_text": {
                        "type": "text",
                        "analyzer": "ik_max_word",
                        "search_analyzer": "ik_smart"
                    },

                    # Vector embedding for k-NN search
                    "semantic_embedding": {
                        "type": "knn_vector",
                        "dimension": 1024,
                        "method": {
                            "name": "hnsw",
                            "space_type": "cosinesimil",
                            "engine": "nmslib",
                            "parameters": {
                                "ef_construction": 128,
                                "m": 16
                            }
                        }
                    },

                    # References
                    "s3_key": {"type": "keyword"},
                    "indexed_at": {"type": "date"}
                }
            }
        }

        # Create index
        response = client.indices.create(
            index=INDEX_NAME,
            body=index_body
        )

        # Get index info for verification
        index_info = client.indices.get(index=INDEX_NAME)

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f'Index {INDEX_NAME} created successfully',
                'details': {
                    'vector_dimension': 1024,
                    'algorithm': 'HNSW with cosine similarity',
                    'chinese_analyzer': 'ik_max_word',
                    'english_analyzer': 'english'
                },
                'response': response
            }, default=str)
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()

        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'type': type(e).__name__
            })
        }