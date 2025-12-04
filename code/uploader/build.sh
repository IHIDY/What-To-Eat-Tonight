#!/bin/bash
set -e

echo "Building uploader Lambda (code only, no external dependencies)..."

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "Current directory: $SCRIPT_DIR"

# Create zip file with only business code
ZIP_PATH="../../infra/modules/lambda/uploader.zip"
echo "Creating zip file at $ZIP_PATH..."
rm -f "$ZIP_PATH"

# Only package app.py (boto3 is provided by Lambda runtime)
zip "$ZIP_PATH" app.py

echo "✓ uploader Lambda package created successfully!"
echo "  Note: boto3 is provided by AWS Lambda runtime"
