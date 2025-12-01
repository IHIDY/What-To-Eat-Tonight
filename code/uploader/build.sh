#!/bin/bash
set -e  # Exit on error

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "Building uploader Lambda..."
echo "Current directory: $(pwd)"

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt -t .

# Create zip file
ZIP_PATH="../../infra/modules/lambda/uploader.zip"
echo "Creating zip file at $ZIP_PATH..."

# Remove old zip if exists
rm -f "$ZIP_PATH"

# Create new zip (exclude build.sh and __pycache__)
zip -r "$ZIP_PATH" . -x "*.sh" "*__pycache__*" "*.pyc"

echo "✅ Build complete: $ZIP_PATH"
