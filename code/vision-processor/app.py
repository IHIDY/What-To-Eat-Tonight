import json
import logging
import os
import base64
import boto3
import time
from datetime import datetime
from openai import OpenAI
from urllib.parse import unquote_plus
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

# Setup logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS clients
s3 = boto3.client('s3')
lambda_client = boto3.client('lambda')
bedrock = boto3.client('bedrock-runtime', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# OpenAI client
client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))

# Lambda function name for self-invocation
FUNCTION_NAME = os.environ.get('AWS_LAMBDA_FUNCTION_NAME')
REGENERATION_DELAY_SECONDS = 10

# OpenSearch configuration
OPENSEARCH_ENDPOINT = os.environ.get('OPENSEARCH_ENDPOINT')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
OPENSEARCH_INDEX = 'recipes'

# Initialize OpenSearch client lazily
_opensearch_client = None

def get_opensearch_client():
    """Create OpenSearch client with AWS4Auth (lazy initialization)"""
    global _opensearch_client

    if _opensearch_client is None:
        if not OPENSEARCH_ENDPOINT:
            logger.warning("OPENSEARCH_ENDPOINT not set, skipping OpenSearch integration")
            return None

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
        logger.info(f"OpenSearch client initialized: {OPENSEARCH_ENDPOINT}")

    return _opensearch_client

# Recipe extraction prompt using your schema (bilingual Chinese/English)
RECIPE_EXTRACTION_PROMPT = """你是一个专业的食谱分析助手。我会提供一张或多张同一道菜的食谱图片，请综合分析所有图片，提取完整的菜谱信息并以 JSON 格式返回。

如果有多张图片，请将它们的信息合并成一个完整的菜谱（例如：第一张是食材清单，第二张是步骤说明）。

**重要：请提供中英文双语信息，以支持中英文搜索功能。**

请按照以下 Schema 提取信息：

```json
{
  "title": "菜名（中文）",
  "title_en": "Recipe name (English translation)",
  "description": "简短描述（中文）",
  "description_en": "Brief description (English translation)",
  "ingredients": [
    {
      "name": "食材名（中文）",
      "name_en": "Ingredient name (English)",
      "amount": "用量",
      "note": "备注（可选）"
    }
  ],
  "seasonings": [
    {
      "name": "调味料名（中文）",
      "name_en": "Seasoning name (English)",
      "amount": "用量"
    }
  ],
  "steps": [
    {
      "order": 步骤序号,
      "action": "动作（中文）",
      "action_en": "Action (English)",
      "details": "详细说明（中文）",
      "details_en": "Detailed instructions (English)",
      "duration": "时长（可选）"
    }
  ],
  "tips": ["烹饪技巧（中文）"],
  "tips_en": ["Cooking tips (English)"],
  "category": ["分类标签（中文，如：川菜、家常菜、快手菜）"],
  "category_en": ["Category tags (English, e.g., Sichuan cuisine, home cooking, quick meal)"],
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
    "health_tags": ["健康标签（中文，如：高蛋白、低脂、素食）"],
    "health_tags_en": ["Health tags (English, e.g., high protein, low fat, vegetarian)"],
    "health_risk_notes": ["健康提示（中文）"],
    "health_risk_notes_en": ["Health notes (English)"]
  },
  "semantic_text": "用于语义搜索的自然语言描述（中英文混合）。请将菜谱信息以自然段落形式描述，包括：菜名、简介、主要食材、烹饪方法、适用场景、健康特点等。示例：'红烧肉 (Braised Pork Belly) 是一道经典的中式菜肴，适合宴客和节日聚餐。主要食材包括五花肉、冰糖、生抽、老抽、料酒等。制作过程包括切块、焯水、炒糖色、慢炖等步骤。这道菜口感软糯，肥而不腻，富含蛋白质和脂肪，适合冬季食用。属于川菜、家常菜。'"
}
```

注意事项：
1. **必须提供中英文双语**：所有文本字段都需要中文版本和对应的英文翻译版本
2. 如果图片中没有某项信息，请合理推断或设为 null/空数组
3. difficulty 根据步骤复杂度判断：easy（简单），medium（中等），hard（困难）
4. health_tags 请根据食材判断（如：高蛋白、低脂、高纤维、素食、无麸质等）
5. category 请包含：菜系（如川菜、粤菜）、主食材（如鸡肉、猪肉、海鲜）、烹饪方式（如炒、蒸、炸）、场景（如家常菜、宴客菜、快手菜）
6. **nutrition_estimate 请根据食材种类和用量进行合理估算**：
   - 参考常见食材的营养数据库
   - 考虑烹饪方式（油炸会增加脂肪，蒸煮相对低卡）
   - 按照 metadata.servings 计算每份的营养
   - 如果无法合理估算某项，可以设为 null
   - 调味料（盐、酱油等）也要计入钠含量
7. **英文翻译要准确且地道**：菜名翻译尽量使用常见的英文名称（如"宫保鸡丁" → "Kung Pao Chicken"）

请直接返回 JSON，不要添加任何解释文字。"""


def handler(event, context):
    """Handle S3 events, regeneration checks, or clean up JSON files"""
    logger.info(f"Received event: {json.dumps(event)}")

    try:
        # Check if this is a scheduled regeneration check (from Lambda self-invocation)
        if event.get('action') == 'check_regeneration':
            return handle_regeneration_check(event)

        # Otherwise, handle S3 events
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
        # Only process when .complete marker file is uploaded
        if not image_key.endswith('.complete'):
            logger.info(f"Skipping non-marker file: {image_key}")
            return

        # Get upload_id folder from marker file key
        # images/raw/20251202-034138-03e81b1c/.complete -> images/raw/20251202-034138-03e81b1c/
        parts = image_key.split('/')
        if len(parts) < 3:
            logger.error(f"Invalid marker key format: {image_key}")
            return

        folder_prefix = '/'.join(parts[:3]) + '/'
        logger.info(f"Marker file detected, processing all images in folder: {folder_prefix}")

        # List all images in the same folder
        response = s3.list_objects_v2(Bucket=bucket, Prefix=folder_prefix)

        if 'Contents' not in response:
            logger.warning(f"No images found in folder: {folder_prefix}")
            return

        # Collect all image files (skip non-image files and marker file)
        image_keys = [
            obj['Key'] for obj in response['Contents']
            if obj['Key'].lower().endswith(('.png', '.jpg', '.jpeg'))
        ]

        if not image_keys:
            logger.warning(f"No valid images found in folder: {folder_prefix}")
            return

        logger.info(f"Found {len(image_keys)} images: {image_keys}")

        # Delete the marker file after confirming images exist
        try:
            s3.delete_object(Bucket=bucket, Key=image_key)
            logger.info(f"Deleted marker file: {image_key}")
        except Exception as e:
            logger.warning(f"Failed to delete marker file: {str(e)}")

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
            max_completion_tokens=16000,
            temperature=0.2,
            response_format={"type": "json_object"}
        )

        # Extract response text
        logger.info(f"Completion object: finish_reason={completion.choices[0].finish_reason if completion.choices else 'NO_CHOICES'}")

        response_text = completion.choices[0].message.content

        if response_text is None:
            logger.error(f"OpenAI returned None content! Full response: {completion.model_dump_json()}")
            raise ValueError("OpenAI returned None content")

        response_text = response_text.strip()
        logger.info(f"Response text length: {len(response_text)} characters")

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

        # Index to OpenSearch with embedding
        index_recipe_to_opensearch(bucket, json_key, recipe_json)

        return {'json_key': json_key, 'image_count': len(image_keys)}

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {str(e)}")
        logger.error(f"Response length: {len(response_text)} characters")
        logger.error(f"Response (first 1000 chars): {response_text[:1000]}")
        logger.error(f"Response (last 500 chars): {response_text[-500:]}")
        raise
    except Exception as e:
        logger.error(f"Failed to process: {str(e)}")
        raise


def cleanup_recipe_json(bucket, image_key):
    """Handle image deletion: mark for regeneration instead of immediate processing"""
    try:
        # Get upload_id folder from image_key
        parts = image_key.split('/')
        if len(parts) < 3:
            logger.error(f"Invalid image key format: {image_key}")
            return

        folder_prefix = '/'.join(parts[:3]) + '/'
        upload_id = parts[2]

        logger.info(f"Image deleted: {image_key}, marking for regeneration")

        # Check if there are any remaining images
        response = s3.list_objects_v2(Bucket=bucket, Prefix=folder_prefix)
        remaining_images = []
        if 'Contents' in response:
            remaining_images = [
                obj['Key'] for obj in response['Contents']
                if obj['Key'].lower().endswith(('.png', '.jpg', '.jpeg'))
            ]

        json_key = generate_json_key(image_key)

        if remaining_images:
            # Still have images - create/update pending regeneration marker
            marker_key = f"{folder_prefix}.pending-regeneration"
            current_time = datetime.utcnow().isoformat()

            s3.put_object(
                Bucket=bucket,
                Key=marker_key,
                Body=current_time.encode('utf-8'),
                ContentType='text/plain'
            )
            logger.info(f"Created/updated regeneration marker: {marker_key} at {current_time}")

            # Schedule delayed Lambda invocation
            schedule_regeneration_check(bucket, upload_id)

        else:
            # No images left - delete JSON immediately
            logger.info(f"No remaining images, deleting JSON: {json_key}")
            try:
                s3.delete_object(Bucket=bucket, Key=json_key)
                logger.info("JSON deleted successfully")
            except:
                pass

            # Delete from OpenSearch
            delete_recipe_from_opensearch(upload_id)

            # Delete empty folder
            json_folder_prefix = json_key.rsplit('/', 1)[0] + '/'
            cleanup_empty_folder(bucket, json_folder_prefix)

    except Exception as e:
        logger.error(f"Cleanup marking failed: {str(e)}", exc_info=True)


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
    Generate JSON file path from image key or marker file
    images/raw/20251202-034138-03e81b1c/image-000.png -> recipes/json/20251202-034138-03e81b1c.json
    images/raw/20251202-034138-03e81b1c/.complete -> recipes/json/20251202-034138-03e81b1c.json
    """
    parts = image_key.split('/')
    if len(parts) >= 3:
        upload_id = parts[2]
        return f"recipes/json/{upload_id}.json"
    else:
        filename = image_key.replace('/', '_').rsplit('.', 1)[0]
        return f"recipes/json/{filename}.json"


def schedule_regeneration_check(bucket, upload_id):
    """Schedule a delayed Lambda invocation to check for regeneration"""
    try:
        scheduled_time = datetime.utcnow().timestamp() + REGENERATION_DELAY_SECONDS

        payload = {
            'action': 'check_regeneration',
            'bucket': bucket,
            'upload_id': upload_id,
            'scheduled_time': scheduled_time
        }

        # Asynchronous invocation (Event type)
        lambda_client.invoke(
            FunctionName=FUNCTION_NAME,
            InvocationType='Event',
            Payload=json.dumps(payload)
        )

        logger.info(f"Scheduled regeneration check in {REGENERATION_DELAY_SECONDS}s for {upload_id}")

    except Exception as e:
        logger.error(f"Failed to schedule regeneration check: {str(e)}", exc_info=True)


def handle_regeneration_check(event):
    """Handle scheduled regeneration check"""
    bucket = event['bucket']
    upload_id = event['upload_id']
    scheduled_time = event['scheduled_time']

    logger.info(f"Regeneration check triggered for {upload_id}")

    # Wait until scheduled time
    current_time = datetime.utcnow().timestamp()
    if current_time < scheduled_time:
        wait_time = scheduled_time - current_time
        logger.info(f"Waiting {wait_time:.2f}s before checking...")
        time.sleep(wait_time)

    folder_prefix = f"images/raw/{upload_id}/"
    marker_key = f"{folder_prefix}.pending-regeneration"

    try:
        # Check if marker still exists
        marker_obj = s3.get_object(Bucket=bucket, Key=marker_key)
        marker_time_str = marker_obj['Body'].read().decode('utf-8')
        marker_time = datetime.fromisoformat(marker_time_str)

        # Check if enough time has passed
        time_diff = (datetime.utcnow() - marker_time).total_seconds()

        if time_diff >= REGENERATION_DELAY_SECONDS:
            logger.info(f"Regenerating JSON for {upload_id} (waited {time_diff:.2f}s)")

            # Regenerate JSON with remaining images
            regenerate_recipe_json(bucket, folder_prefix, upload_id)

            # Delete marker file
            s3.delete_object(Bucket=bucket, Key=marker_key)
            logger.info(f"Deleted regeneration marker: {marker_key}")
        else:
            logger.info(f"Skipping regeneration for {upload_id} (only {time_diff:.2f}s passed, marker was updated)")

    except s3.exceptions.NoSuchKey:
        logger.info(f"Marker file already processed or deleted: {marker_key}")
    except Exception as e:
        logger.error(f"Regeneration check failed: {str(e)}", exc_info=True)

    return {'statusCode': 200, 'body': json.dumps({'message': 'Check completed'})}


def regenerate_recipe_json(bucket, folder_prefix, upload_id):
    """Regenerate recipe JSON from remaining images"""
    try:
        # List remaining images
        response = s3.list_objects_v2(Bucket=bucket, Prefix=folder_prefix)

        remaining_images = []
        if 'Contents' in response:
            remaining_images = [
                obj['Key'] for obj in response['Contents']
                if obj['Key'].lower().endswith(('.png', '.jpg', '.jpeg'))
            ]

        if not remaining_images:
            logger.warning(f"No images to regenerate for {upload_id}")
            return

        logger.info(f"Regenerating with {len(remaining_images)} images: {remaining_images}")

        # Download and encode all images
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
            max_completion_tokens=16000,
            temperature=0.2,
            response_format={"type": "json_object"}
        )

        logger.info(f"Regeneration - Completion: finish_reason={completion.choices[0].finish_reason if completion.choices else 'NO_CHOICES'}")

        response_text = completion.choices[0].message.content

        if response_text is None:
            logger.error(f"Regeneration - OpenAI returned None! Full response: {completion.model_dump_json()}")
            raise ValueError("OpenAI returned None content in regeneration")

        response_text = response_text.strip()
        logger.info(f"Regeneration - Response length: {len(response_text)} chars")

        # Remove markdown code block markers
        if response_text.startswith('```'):
            response_text = response_text.split('```')[1]
            if response_text.startswith('json'):
                response_text = response_text[4:]
            response_text = response_text.strip()

        recipe_json = json.loads(response_text)
        logger.info(f"Regenerated recipe: {recipe_json.get('title', 'Unknown')}")

        # Save to S3
        json_key = f"recipes/json/{upload_id}.json"
        s3.put_object(
            Bucket=bucket,
            Key=json_key,
            Body=json.dumps(recipe_json, ensure_ascii=False, indent=2).encode('utf-8'),
            ContentType='application/json',
            Metadata={
                'source-folder': folder_prefix,
                'image-count': str(len(remaining_images)),
                'model': 'gpt-5.1',
                'regenerated': 'true'
            }
        )

        logger.info(f"Regenerated JSON saved to: s3://{bucket}/{json_key}")

        # Re-index to OpenSearch with new embedding
        index_recipe_to_opensearch(bucket, json_key, recipe_json)

    except json.JSONDecodeError as e:
        logger.error(f"Regeneration JSON parse error: {str(e)}")
        logger.error(f"Response (first 1000 chars): {response_text[:1000]}")
        logger.error(f"Response (last 500 chars): {response_text[-500:]}")
        raise
    except Exception as e:
        logger.error(f"Regeneration failed: {str(e)}", exc_info=True)
        raise


def generate_bedrock_embedding(text):
    """Generate embedding using AWS Bedrock Titan Embeddings v2"""
    try:
        # Call Bedrock Titan Embeddings model
        response = bedrock.invoke_model(
            modelId='amazon.titan-embed-text-v2:0',
            body=json.dumps({
                "inputText": text,
                "dimensions": 1024,
                "normalize": True
            })
        )

        # Parse response
        response_body = json.loads(response['body'].read())
        embedding = response_body['embedding']

        logger.info(f"Generated embedding: {len(embedding)} dimensions")
        return embedding

    except Exception as e:
        logger.error(f"Failed to generate Bedrock embedding: {str(e)}", exc_info=True)
        raise


def index_recipe_to_opensearch(bucket, json_key, recipe_json):
    """Index or update recipe in OpenSearch with embedding"""
    try:
        os_client = get_opensearch_client()
        if not os_client:
            logger.warning("OpenSearch client not available, skipping indexing")
            return

        # Extract recipe_id from JSON key
        recipe_id = json_key.split('/')[-1].replace('.json', '')

        # Get semantic_text for embedding
        semantic_text = recipe_json.get('semantic_text', '')
        if not semantic_text:
            logger.warning(f"No semantic_text found for {recipe_id}, skipping embedding")
            return

        # Generate embedding using Bedrock
        logger.info(f"Generating embedding for recipe {recipe_id}...")
        embedding = generate_bedrock_embedding(semantic_text)

        # Prepare document for OpenSearch
        doc = {
            'recipe_id': recipe_id,
            'title': recipe_json.get('title'),
            'title_en': recipe_json.get('title_en'),
            'description': recipe_json.get('description'),
            'description_en': recipe_json.get('description_en'),
            'ingredients': recipe_json.get('ingredients', []),
            'seasonings': recipe_json.get('seasonings', []),
            'category': recipe_json.get('category', []),
            'category_en': recipe_json.get('category_en', []),
            'health_tags': recipe_json.get('health', {}).get('health_tags', []),
            'health_tags_en': recipe_json.get('health', {}).get('health_tags_en', []),
            'difficulty': recipe_json.get('metadata', {}).get('difficulty'),
            'servings': recipe_json.get('metadata', {}).get('servings'),
            'semantic_text': semantic_text,
            'semantic_embedding': embedding,
            's3_key': json_key,
            'indexed_at': datetime.utcnow().isoformat()
        }

        # Index to OpenSearch (will update if document with same ID exists)
        os_client.index(
            index=OPENSEARCH_INDEX,
            id=recipe_id,
            body=doc,
            refresh=True  # Make immediately searchable
        )

        logger.info(f"Successfully indexed recipe {recipe_id} to OpenSearch")

    except Exception as e:
        logger.error(f"Failed to index recipe to OpenSearch: {str(e)}", exc_info=True)
        # Don't raise - we don't want OpenSearch failures to break the main flow


def delete_recipe_from_opensearch(recipe_id):
    """Delete recipe from OpenSearch"""
    try:
        os_client = get_opensearch_client()
        if not os_client:
            logger.warning("OpenSearch client not available, skipping deletion")
            return

        os_client.delete(
            index=OPENSEARCH_INDEX,
            id=recipe_id
        )

        logger.info(f"Deleted recipe {recipe_id} from OpenSearch")

    except Exception as e:
        logger.error(f"Failed to delete recipe from OpenSearch: {str(e)}", exc_info=True)
        # Don't raise - OpenSearch errors shouldn't break the main flow
