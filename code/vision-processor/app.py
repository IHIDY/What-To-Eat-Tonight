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
RECIPE_EXTRACTION_PROMPT = """你是一个专业的食谱分析助手。我会提供一张或多张同一道菜的食谱图片，请综合分析所有图片，提取完整的菜谱信息并以 JSON 格式返回。

如果有多张图片，请将它们的信息合并成一个完整的菜谱（例如：第一张是食材清单，第二张是步骤说明）。

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
      "calories": 估算的每份卡路里（kcal），基于食材和用量,
      "protein_g": 估算的蛋白质克数,
      "fat_g": 估算的脂肪克数,
      "carbs_g": 估算的碳水化合物克数,
      "fiber_g": 估算的膳食纤维克数,
      "sodium_mg": 估算的钠含量（毫克）
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
5. **nutrition_estimate 请根据食材种类和用量进行合理估算**：
   - 参考常见食材的营养数据库
   - 考虑烹饪方式（油炸会增加脂肪，蒸煮相对低卡）
   - 按照 metadata.servings 计算每份的营养
   - 如果无法合理估算某项，可以设为 null
   - 调味料（盐、酱油等）也要计入钠含量

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
    """Extract recipe information from all images in the same folder using GPT-5.1 multimodal model"""
    logger.info(f"Triggered by: s3://{bucket}/{image_key}")

    try:
        # Get upload_id folder from image_key
        # images/raw/20251202-034138-03e81b1c/image-000.png -> images/raw/20251202-034138-03e81b1c/
        parts = image_key.split('/')
        if len(parts) < 3:
            logger.error(f"Invalid image key format: {image_key}")
            return

        folder_prefix = '/'.join(parts[:3]) + '/'
        logger.info(f"Processing all images in folder: {folder_prefix}")

        # List all images in the same folder
        response = s3.list_objects_v2(Bucket=bucket, Prefix=folder_prefix)

        if 'Contents' not in response:
            logger.warning(f"No images found in folder: {folder_prefix}")
            return

        # Collect all image files (skip non-image files)
        image_keys = [
            obj['Key'] for obj in response['Contents']
            if obj['Key'].lower().endswith(('.png', '.jpg', '.jpeg'))
        ]

        if not image_keys:
            logger.warning(f"No valid images found in folder: {folder_prefix}")
            return

        # Sort images to get consistent ordering
        sorted_images = sorted(image_keys)

        # Only process if this is the last image (highest index)
        # This ensures all images are uploaded before processing
        last_image = sorted_images[-1]
        if image_key != last_image:
            logger.info(f"Skipping processing: waiting for last image. Current: {image_key}, Last: {last_image}")
            return

        logger.info(f"Processing last uploaded image, found {len(sorted_images)} images: {sorted_images}")

        # Continue with existing logic using sorted_images
        response = s3.list_objects_v2(Bucket=bucket, Prefix=folder_prefix)

        if 'Contents' not in response:
            logger.warning(f"No images found in folder: {folder_prefix}")
            return

        # Collect all image files (skip non-image files)
        image_keys = [
            obj['Key'] for obj in response['Contents']
            if obj['Key'].lower().endswith(('.png', '.jpg', '.jpeg'))
        ]

        if not image_keys:
            logger.warning(f"No valid images found in folder: {folder_prefix}")
            return

        logger.info(f"Found {len(image_keys)} images: {image_keys}")

        # Download and encode all images
        image_contents = []
        for img_key in sorted(image_keys):  # Sort to maintain consistent order
            img_response = s3.get_object(Bucket=bucket, Key=img_key)
            img_bytes = img_response['Body'].read()
            img_base64 = base64.b64encode(img_bytes).decode('utf-8')

            # Determine image type
            img_type = "image/jpeg"
            if img_key.lower().endswith('.png'):
                img_type = "image/png"

            image_contents.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{img_type};base64,{img_base64}"
                }
            })

        # Build message content with prompt + all images
        message_content = [{"type": "text", "text": RECIPE_EXTRACTION_PROMPT}]
        message_content.extend(image_contents)

        logger.info(f"Calling OpenAI GPT-5.1 API with {len(image_contents)} images...")

        # Call OpenAI API with GPT-5.1 multimodal model
        completion = client.chat.completions.create(
            model="gpt-5.1",
            messages=[
                {
                    "role": "user",
                    "content": message_content
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
                'source-folder': folder_prefix,
                'image-count': str(len(image_keys)),
                'model': 'gpt-5.1'
            }
        )

        logger.info(f"Saved to: s3://{bucket}/{json_key}")
        return {'json_key': json_key, 'image_count': len(image_keys)}

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {str(e)}")
        logger.error(f"Response: {response_text[:500]}")
        raise
    except Exception as e:
        logger.error(f"Failed to process: {str(e)}")
        raise


def cleanup_recipe_json(bucket, image_key):
    """Handle image deletion: regenerate JSON with remaining images or delete if folder is empty"""
    try:
        # Get upload_id folder from image_key
        parts = image_key.split('/')
        if len(parts) < 3:
            logger.error(f"Invalid image key format: {image_key}")
            return

        folder_prefix = '/'.join(parts[:3]) + '/'
        logger.info(f"Image deleted: {image_key}, checking folder: {folder_prefix}")

        # List remaining images in the same folder
        response = s3.list_objects_v2(Bucket=bucket, Prefix=folder_prefix)

        # Collect remaining image files
        remaining_images = []
        if 'Contents' in response:
            remaining_images = [
                obj['Key'] for obj in response['Contents']
                if obj['Key'].lower().endswith(('.png', '.jpg', '.jpeg'))
            ]

        json_key = generate_json_key(image_key)

        if remaining_images:
            # Still have images, regenerate JSON with remaining images
            logger.info(f"Found {len(remaining_images)} remaining images, regenerating recipe...")
            logger.info(f"Remaining images: {remaining_images}")

            # Reprocess with remaining images (same logic as process_recipe_image)
            image_contents = []
            for img_key in sorted(remaining_images):
                img_response = s3.get_object(Bucket=bucket, Key=img_key)
                img_bytes = img_response['Body'].read()
                img_base64 = base64.b64encode(img_bytes).decode('utf-8')

                img_type = "image/jpeg"
                if img_key.lower().endswith('.png'):
                    img_type = "image/png"

                image_contents.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{img_type};base64,{img_base64}"
                    }
                })

            # Build message content
            message_content = [{"type": "text", "text": RECIPE_EXTRACTION_PROMPT}]
            message_content.extend(image_contents)

            logger.info(f"Calling OpenAI GPT-5.1 API with {len(image_contents)} images...")

            # Call OpenAI API
            completion = client.chat.completions.create(
                model="gpt-5.1",
                messages=[
                    {
                        "role": "user",
                        "content": message_content
                    }
                ],
                max_completion_tokens=2000,
                temperature=0.2
            )

            response_text = completion.choices[0].message.content.strip()

            # Remove markdown code block markers
            if response_text.startswith('```'):
                response_text = response_text.split('```')[1]
                if response_text.startswith('json'):
                    response_text = response_text[4:]
                response_text = response_text.strip()

            recipe_json = json.loads(response_text)
            logger.info(f"Re-extracted recipe: {recipe_json.get('title', 'Unknown')}")

            # Update JSON file
            s3.put_object(
                Bucket=bucket,
                Key=json_key,
                Body=json.dumps(recipe_json, ensure_ascii=False, indent=2).encode('utf-8'),
                ContentType='application/json',
                Metadata={
                    'source-folder': folder_prefix,
                    'image-count': str(len(remaining_images)),
                    'model': 'gpt-5.1'
                }
            )

            logger.info(f"Updated JSON with {len(remaining_images)} remaining images")

        else:
            # No images left, delete the JSON file
            logger.info(f"No remaining images, deleting JSON: {json_key}")
            s3.delete_object(Bucket=bucket, Key=json_key)
            logger.info("JSON deleted successfully")

            # Check and delete empty folder
            json_folder_prefix = json_key.rsplit('/', 1)[0] + '/'
            cleanup_empty_folder(bucket, json_folder_prefix)

    except Exception as e:
        logger.error(f"Cleanup/regeneration failed: {str(e)}", exc_info=True)


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
