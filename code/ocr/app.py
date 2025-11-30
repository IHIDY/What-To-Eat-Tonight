import json
import boto3
import os

# Create Textract and S3 clients
textract = boto3.client("textract")
s3 = boto3.client("s3")

def handler(event, context):
    """
    Main Lambda handler for OCR processing.
    
    Expected event format when triggered by API Gateway:
    {
        "bucket": "your-bucket-name",
        "key": "path/to/image.jpg"
    }

    OR when triggered by S3 event notification:
    {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": "your-bucket-name"},
                    "object": {"key": "path/to/image.jpg"}
                }
            }
        ]
    }
    """
    
    # Extract bucket and key from event
    if "Records" in event:  
        # Triggered by S3 event
        bucket = event["Records"][0]["s3"]["bucket"]["name"]
        key = event["Records"][0]["s3"]["object"]["key"]
    else:
        # Triggered manually or via API Gateway
        bucket = event.get("bucket")
        key = event.get("key")

    if not bucket or not key:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Missing bucket or key"})
        }

    # Call Amazon Textract for OCR
    response = textract.detect_document_text(
        Document={
            "S3Object": {
                "Bucket": bucket,
                "Name": key
            }
        }
    )

    # Extract detected text blocks
    extracted_text = []
    for block in response.get("Blocks", []):
        if block["BlockType"] == "LINE":
            extracted_text.append(block["Text"])

    # Generate output text
    ocr_text = "\n".join(extracted_text)

    # Save OCR output to S3 under `/ocr-output/...`
    output_key = f"ocr-output/{os.path.basename(key)}.txt"

    s3.put_object(
        Bucket=bucket,
        Key=output_key,
        Body=ocr_text.encode("utf-8")
    )

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "OCR completed",
            "bucket": bucket,
            "input_key": key,
            "output_key": output_key,
            "text_preview": ocr_text[:200]  # first 200 chars
        })
    }
