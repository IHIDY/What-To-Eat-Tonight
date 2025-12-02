import json
import logging
import os
import uuid
from datetime import datetime

# logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# read the config from the environment
import boto3
s3 = boto3.client("s3")
BUCKET = os.environ.get("S3_BUCKET_NAME", "what-to-eat-cloud-recipes")

# Presigned URL 过期时间（秒）
PRESIGNED_URL_EXPIRATION = 3600  # 1 hour

def handler(event, context):
    """
    Generate presigned URLs for direct S3 upload.
    Client will use these URLs to upload files directly to S3.

    Request format:
    - Single file: {"file_type": "jpg"}
    - Batch: {"files": [{"file_type": "jpg"}, {"file_type": "png"}]}

    Response format:
    - upload_id: unique session ID
    - urls: array of presigned URLs with metadata
    """
    logger.info(f"Received event: {json.dumps(event)}")

    try:
        # Parse JSON body
        body = event.get("body")
        if not body:
            return error_response(400, "Missing body")

        # Check if body is base64 encoded by API Gateway
        if event.get("isBase64Encoded"):
            import base64
            body = base64.b64decode(body).decode("utf-8")

        # Parse JSON
        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            return error_response(400, f"Invalid JSON: {str(e)}")

        # Generate timestamp folder for this upload session
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        upload_id = f"{timestamp}-{str(uuid.uuid4())[:8]}"

        # Check if batch upload (files array) or single upload
        files = data.get("files")

        if files:
            # Batch upload mode
            logger.info(f"Generating {len(files)} presigned URLs for folder {upload_id}")
            presigned_urls = []

            for idx, file_data in enumerate(files):
                try:
                    result = generate_presigned_url(file_data, idx, upload_id)
                    presigned_urls.append(result)
                except Exception as e:
                    logger.error(f"Failed to generate URL for file {idx}: {str(e)}")
                    return error_response(400, f"Invalid file data at index {idx}: {str(e)}")

            response_data = {
                "upload_id": upload_id,
                "urls": presigned_urls,
                "total": len(files),
                "expires_in": PRESIGNED_URL_EXPIRATION
            }

            return success_response(response_data)
        else:
            # Single upload mode
            file_type = data.get("file_type")
            if not file_type:
                return error_response(400, "Missing file_type")

            result = generate_presigned_url({"file_type": file_type}, 0, upload_id)

            response_data = {
                "upload_id": upload_id,
                "url": result["url"],
                "key": result["key"],
                "fields": result.get("fields"),
                "expires_in": PRESIGNED_URL_EXPIRATION
            }

            return success_response(response_data)

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return error_response(500, f"Internal server error: {str(e)}")


def generate_presigned_url(file_data, index=0, upload_id=None):
    """
    Generate a presigned URL for direct S3 upload

    Args:
        file_data: dict with 'file_type'
        index: file index for naming
        upload_id: unique upload session ID (timestamp-based folder)

    Returns:
        dict with presigned URL and metadata
    """
    # Get file type (default to jpg)
    file_type = file_data.get("file_type", "jpg").lower()

    content_type_map = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp"
    }

    if file_type not in content_type_map:
        raise ValueError(f"Unsupported file type: {file_type}. Supported: {', '.join(content_type_map.keys())}")

    # Generate file name - store in timestamped folder
    # Format: images/raw/20251201-143022-a1b2c3d4/image-001.jpg
    file_name = f"image-{index:03d}.{file_type}"
    file_key = f"images/raw/{upload_id}/{file_name}"

    # Generate presigned URL for PUT operation
    logger.info(f"Generating presigned URL for s3://{BUCKET}/{file_key}")

    try:
        presigned_url = s3.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': BUCKET,
                'Key': file_key,
                'ContentType': content_type_map[file_type]
            },
            ExpiresIn=PRESIGNED_URL_EXPIRATION,
            HttpMethod='PUT'
        )
    except Exception as e:
        logger.error(f"Failed to generate presigned URL: {str(e)}")
        raise ValueError(f"Failed to generate presigned URL: {str(e)}")

    return {
        "url": presigned_url,
        "key": file_key,
        "bucket": BUCKET,
        "file_type": file_type,
        "content_type": content_type_map[file_type],
        "index": index,
        "method": "PUT"
    }


def success_response(data):
    """Return a successful response with CORS headers"""
    return {
        "statusCode": 200,
        "headers": {
            "Access-Control-Allow-Origin": "*",
            "Content-Type": "application/json"
        },
        "body": json.dumps(data)
    }


def error_response(status_code, message):
    """Return an error response with CORS headers"""
    return {
        "statusCode": status_code,
        "headers": {
            "Access-Control-Allow-Origin": "*",
            "Content-Type": "application/json"
        },
        "body": json.dumps({"error": message})
    }