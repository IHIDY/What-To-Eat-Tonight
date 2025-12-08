#!/bin/bash

echo "Building chat Lambda (uses shared Layer for dependencies)..."

# Get current directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
echo "Current directory: $SCRIPT_DIR"

# Target zip path
TARGET_ZIP="$SCRIPT_DIR/../../infra/modules/lambda/chat.zip"

# Clean up old zip
rm -f "$TARGET_ZIP"

# Create zip with just the app code
echo "Creating zip file at $TARGET_ZIP..."
cd "$SCRIPT_DIR"
zip -q "$TARGET_ZIP" app.py

echo "✓ chat Lambda package created successfully!"
echo "  Note: Dependencies are provided by Lambda Layer"