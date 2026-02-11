import hashlib
import json
import os
import secrets
import time

import boto3

HASHED_PASSWORD = os.environ.get("HASHED_PASSWORD", "")
DYNAMODB_TABLE_NAME = os.environ.get("DYNAMODB_TABLE_NAME", "")
TOKEN_TTL_SECONDS = 86400  # 24 hours

dynamodb = boto3.client("dynamodb")


def handler(event, context):
    headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
    }

    try:
        body = json.loads(event.get("body", "{}"))
        password = body.get("password", "")

        if not password:
            return {
                "statusCode": 400,
                "headers": headers,
                "body": json.dumps({"error": "Password is required"}),
            }

        input_hash = hashlib.sha256(password.encode()).hexdigest()

        if input_hash != HASHED_PASSWORD:
            return {
                "statusCode": 401,
                "headers": headers,
                "body": json.dumps({"error": "Unauthorized"}),
            }

        # Generate token
        token = secrets.token_hex(32)

        # Store token in DynamoDB with TTL
        if DYNAMODB_TABLE_NAME:
            ttl = int(time.time()) + TOKEN_TTL_SECONDS
            dynamodb.put_item(
                TableName=DYNAMODB_TABLE_NAME,
                Item={
                    "metric_type": {"S": "auth_token"},
                    "metric_id": {"S": token},
                    "ttl": {"N": str(ttl)},
                },
            )

        return {
            "statusCode": 200,
            "headers": headers,
            "body": json.dumps({"token": token}),
        }

    except Exception as e:
        print(f"Login error: {e}")
        return {
            "statusCode": 500,
            "headers": headers,
            "body": json.dumps({"error": "Internal server error"}),
        }
