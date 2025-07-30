#!/bin/bash

# Build Docker image
docker build -t mcp-croit-ceph:latest .
docker image tag mcp-croit-ceph:latest croit/mcp-croit-ceph

echo "Docker image built!"
echo ""
echo "Usage:"
echo "1. Add to Claude Desktop config (~/.config/claude/config.json):"
echo ""
cat << 'EOF'
{
  "mcpServers": {
    "mcp-croit-ceph": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "-e", "CROIT_HOST=http://demo-cluster-vlan106.int.croit.io:8080",
        "-e", "CROIT_API_TOKEN=your-token-here",
        "mcp-croit-ceph:latest"
      ]
    }
  }
}
EOF
