#!/bin/bash
set -e

echo "Building vision-processor Lambda (code only, dependencies in Layer)..."

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "Current directory: $SCRIPT_DIR"

# Create zip file with only business code (no dependencies)
ZIP_PATH="../../infra/modules/lambda/vision-processor.zip"
echo "Creating zip file at $ZIP_PATH..."
rm -f "$ZIP_PATH"

# Only package app.py (dependencies are in Lambda Layer)
zip "$ZIP_PATH" app.py

echo "✓ vision-processor Lambda package created successfully!"
echo "  Note: Dependencies are provided by Lambda Layer"