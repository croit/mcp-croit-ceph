#!/bin/bash

# Test script for MCP Croit Ceph with local OpenAPI spec

echo "🚀 MCP Croit Ceph - Local Testing Script"
echo "========================================="
echo

# Check if OpenAPI spec exists
if [ ! -f "openapi.json" ]; then
    echo "❌ Error: openapi.json not found in current directory"
    exit 1
fi

echo "✅ Found openapi.json"

# Build Docker image
echo
echo "📦 Building Docker image..."
docker build -t mcp-croit-ceph:test .

if [ $? -ne 0 ]; then
    echo "❌ Docker build failed"
    exit 1
fi

echo "✅ Docker image built successfully"

# Test scenarios
echo
echo "🧪 Running test scenarios..."
echo

# Test 1: Show help
echo "Test 1: Show help and available options"
docker run --rm mcp-croit-ceph:test --help

# Test 2: Test with local OpenAPI spec (no API credentials needed)
echo
echo "Test 2: Hybrid mode with local OpenAPI spec"
docker run --rm \
    -v $(pwd)/openapi.json:/config/openapi.json:ro \
    -e MCP_ARGS="--mode hybrid --openapi-file /config/openapi.json --no-permission-check" \
    mcp-croit-ceph:test || true

# Test 3: List tool count in different modes
echo
echo "Test 3: Tool count comparison"
echo "--------------------------------"

for mode in hybrid base_only categories_only; do
    echo -n "$mode mode: "
    docker run --rm \
        -v $(pwd)/openapi.json:/config/openapi.json:ro \
        -e CROIT_HOST="http://dummy" \
        -e CROIT_API_TOKEN="dummy" \
        -e MCP_ARGS="--mode $mode --openapi-file /config/openapi.json --no-permission-check" \
        mcp-croit-ceph:test 2>&1 | grep -o "Generated [0-9]* tools" | head -1 || echo "Check logs for tool count"
done

# Test 4: Interactive testing with docker-compose
echo
echo "Test 4: Interactive testing setup"
echo "--------------------------------"
echo "To test interactively with your Croit cluster:"
echo
echo "1. Set your credentials:"
echo "   export CROIT_HOST='https://your-croit-cluster'"
echo "   export CROIT_API_TOKEN='your-api-token'"
echo
echo "2. Run with docker-compose:"
echo "   docker-compose -f docker-compose.test.yml up"
echo
echo "3. Or run directly with Docker:"
echo "   docker run -it --rm \\"
echo "     -v \$(pwd)/openapi.json:/config/openapi.json:ro \\"
echo "     -e CROIT_HOST=\"\$CROIT_HOST\" \\"
echo "     -e CROIT_API_TOKEN=\"\$CROIT_API_TOKEN\" \\"
echo "     -e MCP_ARGS=\"--mode hybrid --openapi-file /config/openapi.json\" \\"
echo "     mcp-croit-ceph:test"
echo
echo "✅ Test setup complete!"