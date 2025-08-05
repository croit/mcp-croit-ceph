# MCP croit Ceph

Model Context Protocol (MCP) server for croit Ceph cluster management. Dynamically generates tools from the extensive croit OpenAPI specifications.

## Important

Please do not use this tool for production.
It's a work in progress and allows your AI to potentially harm your cluster!

## Features

- 🔄 Auto-discovers API endpoints from your croit Ceph installation
- 🔐 Takes care of the Bearer token authentication
- 🛠️ Simple configuration - just provide host and token
- 📡 Full REST API access through MCP tools

## Quick Start

```bash
docker run --rm -i \
  -e CROIT_HOST=http://your-cluster.croit.io:8080 \
  -e CROIT_API_TOKEN=your-token \
  mcp-croit-ceph:latest
```

## Claude Desktop Integration

Add to `~/.config/claude/config.json`:

```json
{
  "mcpServers": {
    "mcp-croit-ceph": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-e", "CROIT_HOST=http://your-cluster.awesome.croit.io:8080",
        "-e", "CROIT_API_TOKEN=your-token",
        "mcp-croit-ceph:latest"
      ]
    }
  }
}
```

## Environment Variables

- `CROIT_HOST` - croit cluster URL (required)
- `CROIT_API_TOKEN` - API authentication token (required)

## Developement

Install git pre-commit hooks:

```bash
pre-commit install
```

We use VS Code/Cursor with the [Black Formatter](https://marketplace.visualstudio.com/items?itemName=ms-python.black-formatter)
plugin installed.
The pre-commit hooks will also format the code.

Set up a venv and use let your IDE use it:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
