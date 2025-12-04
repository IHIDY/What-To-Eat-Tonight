import json
import logging
import os
import base64
import boto3
from openai import OpenAI
from urllib.parse import unquote_plus

# Setup logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS clients
s3 = boto3.client('s3')

# OpenAI client
client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))

# Recipe extraction prompt using your schema
RECIPE_EXTRACTION_PROMPT = """你是一个专业的食谱分析助手。请仔细分析这张食谱图片，提取所有相关信息并以 JSON 格式返回。

请按照以下 Schema 提取信息：

```json
{
  "title": "菜名",
  "description": "简短描述",
  "ingredients": [
    {"name": "食材名", "amount": "用量", "note": "备注（可选）"}
  ],
  "seasonings": [
    {"name": "调味料名", "amount": "用量"}
  ],
  "steps": [
    {"order": 步骤序号, "action": "动作", "details": "详细说明", "duration": "时长（可选）"}
  ],
  "tips": ["烹饪技巧"],
  "category": ["分类标签"],
  "metadata": {
    "servings": 份数或null,
    "difficulty": "easy/medium/hard",
    "from_image": true
  },
  "health": {
    "nutrition_estimate": {
      "calories": null,
      "protein_g": null,
      "fat_g": null,
      "carbs_g": null,
      "fiber_g": null,
      "sodium_mg": null
    },
    "health_tags": ["健康标签"],
    "health_risk_notes": ["健康提示"]
  }
}
```

注意事项：
1. 如果图片中没有某项信息，请合理推断或设为 null/空数组
2. difficulty 根据步骤复杂度判断
3. health_tags 请根据食材判断
4. category 请包含：菜系、主食材、烹饪方式、场景

请直接返回 JSON，不要添加任何解释文字。"""


def handler(event, context):
    """Handle S3 events to extract recipe info or clean up JSON files"""
    logger.info(f"Received event: {json.dumps(event)}")

    try:
        for record in event['Records']:
            event_name = record['eventName']
            bucket = record['s3']['bucket']['name']
            key = unquote_plus(record['s3']['object']['key'])

            logger.info(f"Processing: {event_name}, {key}")

            if event_name.startswith('ObjectCreated'):
                process_recipe_image(bucket, key)
            elif event_name.startswith('ObjectRemoved'):
                cleanup_recipe_json(bucket, key)

        return {'statusCode': 200, 'body': json.dumps({'message': 'Success'})}

    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
        raise


def process_recipe_image(bucket, image_key):
    """Extract recipe information using GPT-5.1 multimodal model"""
    logger.info(f"Extracting recipe from: s3://{bucket}/{image_key}")

    try:
        # Download image from S3
        response = s3.get_object(Bucket=bucket, Key=image_key)
        image_bytes = response['Body'].read()
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        # Determine image type
        image_type = "image/jpeg"
        if image_key.lower().endswith('.png'):
            image_type = "image/png"

        logger.info("Calling OpenAI GPT-5.1 API...")

        # Call OpenAI API with GPT-5.1 multimodal model
        completion = client.chat.completions.create(
            model="gpt-5.1",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": RECIPE_EXTRACTION_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{image_type};base64,{image_base64}"
                            }
                        }
                    ]
                }
            ],
            max_completion_tokens=2000,
            temperature=0.2
        )

        # Extract response text
        response_text = completion.choices[0].message.content.strip()

        # Remove markdown code block markers if present
        if response_text.startswith('```'):
            response_text = response_text.split('```')[1]
            if response_text.startswith('json'):
                response_text = response_text[4:]
            response_text = response_text.strip()

        recipe_json = json.loads(response_text)
        logger.info(f"Extracted recipe: {recipe_json.get('title', 'Unknown')}")

        # Generate JSON file path
        # images/raw/abc123/image-000.png -> recipes/json/abc123.json
        json_key = generate_json_key(image_key)

        # Save to S3
        s3.put_object(
            Bucket=bucket,
            Key=json_key,
            Body=json.dumps(recipe_json, ensure_ascii=False, indent=2).encode('utf-8'),
            ContentType='application/json',
            Metadata={
                'source-image': image_key,
                'model': 'gpt-5.1'
            }
        )

        logger.info(f"Saved to: s3://{bucket}/{json_key}")
        return {'json_key': json_key}

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {str(e)}")
        logger.error(f"Response: {response_text[:500]}")
        raise
    except Exception as e:
        logger.error(f"Failed to process: {str(e)}")
        raise


def cleanup_recipe_json(bucket, image_key):
    """Delete the corresponding JSON file when image is removed"""
    try:
        json_key = generate_json_key(image_key)
        logger.info(f"Deleting: s3://{bucket}/{json_key}")

        s3.delete_object(Bucket=bucket, Key=json_key)
        logger.info("Deleted successfully")

        # Check and delete empty folder
        folder_prefix = json_key.rsplit('/', 1)[0] + '/'
        cleanup_empty_folder(bucket, folder_prefix)

    except Exception as e:
        logger.warning(f"Cleanup failed: {str(e)}")


def cleanup_empty_folder(bucket, folder_prefix):
    """Delete empty S3 folder"""
    try:
        response = s3.list_objects_v2(Bucket=bucket, Prefix=folder_prefix, MaxKeys=1)

        if 'Contents' not in response:
            logger.info(f"Folder empty, deleting: {folder_prefix}")
            try:
                s3.delete_object(Bucket=bucket, Key=folder_prefix)
            except:
                pass
    except Exception as e:
        logger.warning(f"Folder cleanup failed: {str(e)}")


def generate_json_key(image_key):
    """
    Generate JSON file path from image key
    images/raw/20251202-034138-03e81b1c/image-000.png
    -> recipes/json/20251202-034138-03e81b1c.json
    """
    parts = image_key.split('/')
    if len(parts) >= 3:
        upload_id = parts[2]
        return f"recipes/json/{upload_id}.json"
    else:
        filename = image_key.replace('/', '_').rsplit('.', 1)[0]
        return f"recipes/json/{filename}.json"
