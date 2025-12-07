#!/usr/bin/env python3
"""
Create OpenSearch index with k-NN mapping for recipe semantic search
"""

import boto3
import json
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

# Configuration
OPENSEARCH_ENDPOINT = "search-what-to-eat-cloud-recipes-bspeiuftiomrmex3eq3ok73af4.us-east-1.es.amazonaws.com"
AWS_REGION = "us-east-1"
INDEX_NAME = "recipes"

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

def create_index():
    """Create recipes index with k-NN mapping"""
    client = get_opensearch_client()

    # Check if index already exists
    if client.indices.exists(index=INDEX_NAME):
        print(f"⚠️  Index '{INDEX_NAME}' already exists")
        response = input("Do you want to delete and recreate it? (yes/no): ")
        if response.lower() == 'yes':
            client.indices.delete(index=INDEX_NAME)
            print(f"✓ Deleted existing index '{INDEX_NAME}'")
        else:
            print("Aborted. Index not modified.")
            return

    # Index settings and mappings
    index_body = {
        "settings": {
            "index": {
                "knn": True,  # Enable k-NN plugin
                "knn.algo_param.ef_search": 100,  # HNSW search quality parameter
                "number_of_shards": 1,
                "number_of_replicas": 0  # Single node, no replicas needed
            }
        },
        "mappings": {
            "properties": {
                # Recipe identification
                "recipe_id": {
                    "type": "keyword"
                },

                # Chinese fields
                "title": {
                    "type": "text",
                    "analyzer": "ik_max_word",  # Chinese text analyzer
                    "search_analyzer": "ik_smart"
                },
                "description": {
                    "type": "text",
                    "analyzer": "ik_max_word",
                    "search_analyzer": "ik_smart"
                },

                # English fields
                "title_en": {
                    "type": "text",
                    "analyzer": "english"
                },
                "description_en": {
                    "type": "text",
                    "analyzer": "english"
                },

                # Ingredients and seasonings
                "ingredients": {
                    "type": "keyword"  # Array of strings, exact match
                },
                "seasonings": {
                    "type": "keyword"
                },

                # Categories
                "category": {
                    "type": "keyword"
                },
                "category_en": {
                    "type": "keyword"
                },

                # Health tags
                "health_tags": {
                    "type": "keyword"
                },
                "health_tags_en": {
                    "type": "keyword"
                },

                # Metadata
                "difficulty": {
                    "type": "keyword"
                },
                "servings": {
                    "type": "integer"
                },

                # Semantic search fields
                "semantic_text": {
                    "type": "text",
                    "analyzer": "ik_max_word",
                    "search_analyzer": "ik_smart"
                },

                # Vector embedding for k-NN search
                "semantic_embedding": {
                    "type": "knn_vector",
                    "dimension": 1024,  # Bedrock Titan Embeddings v2 dimension
                    "method": {
                        "name": "hnsw",  # Hierarchical Navigable Small World algorithm
                        "space_type": "cosinesimil",  # Cosine similarity
                        "engine": "nmslib",  # Library for approximate nearest neighbor search
                        "parameters": {
                            "ef_construction": 128,  # Build quality (higher = better but slower)
                            "m": 16  # Number of connections per node
                        }
                    }
                },

                # S3 reference
                "s3_key": {
                    "type": "keyword"
                },

                # Timestamp
                "indexed_at": {
                    "type": "date"
                }
            }
        }
    }

    # Create index
    response = client.indices.create(
        index=INDEX_NAME,
        body=index_body
    )

    print(f"✓ Created index '{INDEX_NAME}' with k-NN mapping")
    print(f"  - Vector dimension: 1024")
    print(f"  - Algorithm: HNSW with cosine similarity")
    print(f"  - Chinese text analyzer: ik_max_word")
    print(f"  - English text analyzer: english")
    print(f"\nResponse: {json.dumps(response, indent=2)}")

    # Verify index creation
    index_info = client.indices.get(index=INDEX_NAME)
    print(f"\n✓ Index verification:")
    print(f"  Settings: {json.dumps(index_info[INDEX_NAME]['settings']['index'], indent=2)}")

if __name__ == "__main__":
    print("Creating OpenSearch index for recipe semantic search...\n")
    try:
        create_index()
        print("\n✅ Index creation completed successfully!")
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()