#!/bin/bash

set -e

echo "Formatting code..."
echo "=================="

# Format Python code with ruff
echo "Formatting Python files with ruff..."
uv run ruff format .
uv run ruff check --fix .

# Format TypeScript/JavaScript files with prettier
echo "Formatting TypeScript/JavaScript files..."
cd client
bunx prettier --write "src/**/*.{ts,tsx,js,jsx,json,css}" 2>/dev/null || {
    echo "Prettier not available, skipping TypeScript formatting"
}
cd ..

echo "✅ Code formatting complete!"