# Lambda Layers

This directory contains Lambda Layers for sharing dependencies across multiple Lambda functions.

## python-deps

Contains Python dependencies shared by Lambda functions:
- `openai` - OpenAI API client

### Building the Layer

```bash
cd python-deps
./build.sh
```

This will create `infra/modules/lambda-layer/python-deps.zip` ready for deployment.

### Layer Structure

Lambda Layers must follow this directory structure:
```
python/
  ├── package1/
  ├── package2/
  └── ...
```

AWS Lambda will automatically add `/opt/python` to the Python path.