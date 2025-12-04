#!/bin/bash
set -e

echo "Building Python dependencies Lambda Layer..."

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "Current directory: $SCRIPT_DIR"

# Clean up previous build
rm -rf python/
mkdir -p python

echo "Installing dependencies for Linux x86_64 (Python 3.12)..."

# Install to python/ directory (Lambda Layer requirement)
pip3 install \
    --platform manylinux2014_x86_64 \
    --target python \
    --implementation cp \
    --python-version 3.12 \
    --only-binary=:all: \
    --upgrade \
    -r requirements.txt

# Create zip file
ZIP_PATH="../../modules/lambda-layer/python-deps.zip"
echo "Creating zip file at $ZIP_PATH..."
rm -f "$ZIP_PATH"

# Lambda Layer expects python/ directory structure
zip -r "$ZIP_PATH" python/ \
    -x "python/__pycache__/*" \
    -x "python/*/__pycache__/*" \
    -x "python/*.pyc" \
    -x "python/*/*.pyc" \
    -x "python/pip/*" \
    -x "python/setuptools/*" \
    -x "python/wheel/*"

echo "✓ Lambda Layer package created successfully!"
echo "  Size: $(du -h "$ZIP_PATH" | cut -f1)"