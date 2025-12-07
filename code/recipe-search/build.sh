#!/bin/bash
set -e

echo "Building recipe-search Lambda (uses shared Layer for dependencies)..."
echo "Current directory: $(pwd)"

# Create zip file with just the code
ZIP_PATH="../../infra/modules/lambda/recipe-search.zip"
echo "Creating zip file at $ZIP_PATH..."

# Remove old zip if exists
rm -f "$ZIP_PATH"

# Create zip with just app.py
zip -j "$ZIP_PATH" app.py

echo "✓ recipe-search Lambda package created successfully!"
echo "  Note: Dependencies are provided by Lambda Layer"
