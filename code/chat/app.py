#!/usr/bin/env python3
"""
Chat Lambda - AI-powered recipe assistant with search capability
Uses OpenAI GPT with function calling to search recipes and provide recommendations
"""

import os
import json
import boto3
from openai import OpenAI
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

# Setup
client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))
bedrock = boto3.client('bedrock-runtime', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
s3 = boto3.client('s3')

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


def search_recipes(query, mode='hybrid', limit=5):
    """
    Search recipes using OpenSearch

    Args:
        query: Search query string
        mode: Search mode ('semantic', 'keyword', 'hybrid')
        limit: Number of results to return

    Returns:
        List of recipe objects with full details
    """
    print(f"Searching recipes: query='{query}', mode={mode}, limit={limit}")

    try:
        # Generate query embedding for semantic search using Bedrock Titan
        query_embedding = None
        if mode in ['semantic', 'hybrid']:
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

        # Build search query
        os_client = get_opensearch_client()

        if mode == 'semantic':
            search_body = {
                "size": limit,
                "_source": ["recipe_id"],
                "query": {
                    "knn": {
                        "semantic_embedding": {
                            "vector": query_embedding,
                            "k": limit
                        }
                    }
                }
            }
        elif mode == 'keyword':
            search_body = {
                "size": limit,
                "_source": ["recipe_id"],
                "query": {
                    "multi_match": {
                        "query": query,
                        "fields": [
                            "title^3", "title_en^3",
                            "description^2", "description_en^2",
                            "semantic_text", "ingredients", "seasonings",
                            "category", "category_en",
                            "health_tags", "health_tags_en"
                        ],
                        "type": "best_fields",
                        "fuzziness": "AUTO"
                    }
                }
            }
        else:  # hybrid
            search_body = {
                "size": limit,
                "_source": ["recipe_id"],
                "query": {
                    "hybrid": {
                        "queries": [
                            {
                                "knn": {
                                    "semantic_embedding": {
                                        "vector": query_embedding,
                                        "k": limit * 2
                                    }
                                }
                            },
                            {
                                "multi_match": {
                                    "query": query,
                                    "fields": [
                                        "title^3", "title_en^3",
                                        "description^2", "description_en^2",
                                        "semantic_text", "ingredients", "seasonings",
                                        "category", "category_en"
                                    ],
                                    "type": "best_fields",
                                    "fuzziness": "AUTO"
                                }
                            }
                        ]
                    }
                }
            }

        # Execute search
        try:
            response = os_client.search(index=OPENSEARCH_INDEX, body=search_body)
        except Exception as e:
            # Fallback if hybrid query not supported
            if mode == 'hybrid':
                print(f"Hybrid query failed, using keyword only: {e}")
                return search_recipes(query, 'keyword', limit)
            raise

        # Fetch full recipes from S3
        recipes = []
        for hit in response['hits']['hits']:
            recipe_id = hit['_source']['recipe_id']

            try:
                json_key = f"recipes/json/{recipe_id}.json"
                s3_response = s3.get_object(Bucket=S3_BUCKET_NAME, Key=json_key)
                recipe_json = json.loads(s3_response['Body'].read().decode('utf-8'))
                recipe_json['search_score'] = hit['_score']
                recipes.append(recipe_json)
            except Exception as e:
                print(f"Error fetching recipe {recipe_id}: {e}")
                continue

        print(f"Found {len(recipes)} recipes")
        return recipes

    except Exception as e:
        print(f"Search error: {e}")
        import traceback
        traceback.print_exc()
        return []


def handler(event, context):
    """
    Lambda handler for chat endpoint

    Accepts POST requests with:
    {
        "message": "User's question about recipes",
        "conversation_history": [...]  // Optional
    }
    """
    try:
        # Parse request
        body = json.loads(event.get('body', '{}'))
        user_message = body.get('message', '').strip()
        conversation_history = body.get('conversation_history', [])

        if not user_message:
            return {
                'statusCode': 400,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'Message is required'})
            }

        print(f"User message: {user_message}")

        # Define tools for OpenAI function calling
        tools = [
            {
                "type": "function",
                "function": {
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
                                "description": "Search mode. Use 'semantic' for concept-based search, 'keyword' for exact matches, 'hybrid' for best results (default).",
                                "default": "hybrid"
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Number of recipes to return (default: 5, max: 10)",
                                "default": 5,
                                "minimum": 1,
                                "maximum": 10
                            }
                        },
                        "required": ["query"]
                    }
                }
            }
        ]

        # Build messages for OpenAI
        messages = [
            {
                "role": "system",
                "content": """You are a helpful recipe assistant. You help users find recipes and provide cooking advice.

When users ask about recipes, use the search_recipes function to find relevant recipes from the database.

After searching, provide:
1. A brief introduction
2. List of recommended recipes with key details (title, difficulty, servings, key ingredients)
3. Brief explanation of why each recipe fits their request
4. Any relevant cooking tips or health considerations

Be conversational and friendly. Support both Chinese and English. Use emojis occasionally to make it engaging."""
            }
        ] + conversation_history + [
            {
                "role": "user",
                "content": user_message
            }
        ]

        # Call OpenAI with function calling
        max_iterations = 3
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            print(f"OpenAI iteration {iteration}")

            # Call OpenAI
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                tools=tools,
                tool_choice="auto"
            )

            response_message = response.choices[0].message
            print(f"OpenAI response: finish_reason={response.choices[0].finish_reason}")

            # Add assistant's response to messages
            # Convert response_message to dict for JSON serialization
            assistant_message = {
                "role": "assistant",
                "content": response_message.content
            }
            if response_message.tool_calls:
                assistant_message["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in response_message.tool_calls
                ]
            messages.append(assistant_message)

            # Check if tool calls are needed
            tool_calls = response_message.tool_calls

            if tool_calls:
                # Execute tool calls
                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments)

                    print(f"Executing function: {function_name} with args: {function_args}")

                    if function_name == 'search_recipes':
                        # Execute search
                        recipes = search_recipes(
                            query=function_args.get('query'),
                            mode=function_args.get('mode', 'hybrid'),
                            limit=function_args.get('limit', 5)
                        )

                        # Add function result to messages
                        messages.append({
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": function_name,
                            "content": json.dumps(recipes, ensure_ascii=False)
                        })

                # Continue loop to get OpenAI's final response
                continue

            else:
                # No tool calls, return the final response
                final_response = response_message.content

                return {
                    'statusCode': 200,
                    'headers': {
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    },
                    'body': json.dumps({
                        'response': final_response,
                        'conversation_history': messages[1:]  # Exclude system message
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