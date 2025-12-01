import base64
import boto3
import json
import logging
import os
import uuid
from datetime import datetime

# logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# read the config from the enviroment
s3 = boto3.client("s3")
BUCKET = os.environ.get("S3_BUCKET_NAME", "what-to-eat-cloud-recipes")

def handler(event, context):
    """
    API Gateway HTTP API receives base64-encoded image file(s).
    Supports both single file upload and batch upload.
    This function decodes and uploads to S3 under 'raw/' directory.
    """
    logger.info(f"Received event: {json.dumps(event)}")

    try:
        # Parse JSON body
        body = event.get("body")
        if not body:
            return error_response(400, "Missing body")

        # Check if body is base64 encoded by API Gateway
        if event.get("isBase64Encoded"):
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
            logger.info(f"Batch upload: {len(files)} files to folder {upload_id}")
            uploaded_files = []
            failed_files = []

            for idx, file_data in enumerate(files):
                try:
                    result = upload_single_file(file_data, idx, upload_id)
                    uploaded_files.append(result)
                except Exception as e:
                    logger.error(f"Failed to upload file {idx}: {str(e)}")
                    failed_files.append({"index": idx, "error": str(e)})

            response_data = {
                "upload_id": upload_id,
                "uploaded": uploaded_files,
                "total": len(files),
                "success_count": len(uploaded_files),
                "failed_count": len(failed_files)
            }

            if failed_files:
                response_data["failed"] = failed_files

            return success_response(response_data)
        else:
            # Single upload mode (backward compatible)
            file_content = data.get("file_base64")
            if not file_content:
                return error_response(400, "Missing file_base64 or files array")

            file_type = data.get("file_type", "jpg")
            result = upload_single_file({"file_base64": file_content, "file_type": file_type}, 0, upload_id)
            result["upload_id"] = upload_id
            return success_response(result)

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return error_response(500, f"Internal server error: {str(e)}")


def upload_single_file(file_data, index=0, upload_id=None):
    """
    Upload a single file to S3

    Args:
        file_data: dict with 'file_base64' and optional 'file_type'
        index: file index for logging
        upload_id: unique upload session ID (timestamp-based folder)

    Returns:
        dict with upload result
    """
    file_content = file_data.get("file_base64")
    if not file_content:
        raise ValueError(f"Missing file_base64 at index {index}")

    # Decode base64
    try:
        binary_data = base64.b64decode(file_content)
    except Exception as e:
        raise ValueError(f"Invalid base64 at index {index}: {str(e)}")

    # Get file type (default to jpg)
    file_type = file_data.get("file_type", "jpg").lower()
    content_type_map = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png"
    }

    if file_type not in content_type_map:
        raise ValueError(f"Unsupported file type: {file_type}. Supported: jpg, jpeg, png")

    # Generate file name - store in timestamped folder
    # Format: images/raw/20250115-143022-a1b2c3d4/image-001.jpg
    file_name = f"image-{index:03d}.{file_type}"
    file_key = f"images/raw/{upload_id}/{file_name}"

    # Upload to S3
    logger.info(f"Uploading file {index} to s3://{BUCKET}/{file_key}")
    s3.put_object(
        Bucket=BUCKET,
        Key=file_key,
        Body=binary_data,
        ContentType=content_type_map[file_type]
    )

    return {
        "key": file_key,
        "bucket": BUCKET,
        "size": len(binary_data),
        "type": file_type,
        "index": index
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
