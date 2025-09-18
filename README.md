# MCP Croit Ceph

An MCP (Model Context Protocol) server for interacting with Croit Ceph clusters through their REST API.

## Features

### Hybrid Mode (Default) - 97% Fewer Tools!

The new hybrid mode reduces the tool count from 580 individual endpoint tools to just **13 tools total**:
- **3 Base tools** for full API access
- **10 Category tools** for common operations (services, maintenance, s3, pools, etc.)

This dramatic reduction improves:
- LLM performance and response times
- Tool discovery and usability
- Memory efficiency
- Startup time

### Tool Generation Modes

1. **`hybrid`** (default): Combines base tools with category tools for optimal balance
2. **`base_only`**: Only 3 base tools for minimal footprint
3. **`categories_only`**: Only category tools for simplified operations
4. **`endpoints_as_tools`**: Legacy mode with 580 individual tools (one per API endpoint)

### Dynamic Features

- **Automatic API Discovery**: Fetches OpenAPI spec from your Croit cluster
- **Permission-Based Filtering**: Only shows tools for accessible API categories
- **Schema Resolution**: Handles `$ref` references automatically
- **Local OpenAPI Support**: Use a local OpenAPI spec file for offline development

## Installation

```bash
# Clone the repository
git clone https://github.com/croit/mcp-croit-ceph.git
cd mcp-croit-ceph

# Install dependencies
pip install -r requirements.txt
```

## Configuration

Set up your environment variables:

```bash
export CROIT_HOST="https://your-croit-cluster.com"
export CROIT_API_TOKEN="your-api-token"
```

Or use a config file at `/config/config.json`:

```json
{
  "host": "https://your-croit-cluster.com",
  "api_token": "your-api-token"
}
```

## Usage

### Basic Usage (Hybrid Mode)

```bash
# Default hybrid mode with permission checking
python mcp-croit-ceph.py
```

### Advanced Options

```bash
# Use local OpenAPI spec file
python mcp-croit-ceph.py --openapi-file openapi.json

# Skip permission checking (faster startup)
python mcp-croit-ceph.py --no-permission-check

# Use only base tools (minimal mode)
python mcp-croit-ceph.py --mode base_only

# Use only category tools
python mcp-croit-ceph.py --mode categories_only

# Legacy mode with all 580 endpoint tools (not recommended)
python mcp-croit-ceph.py --mode endpoints_as_tools

# Customize category tool limits
python mcp-croit-ceph.py --max-category-tools 5
```

## Tool Modes Explained

### Hybrid Mode (Recommended)

Provides the best balance with ~13 tools:

**Base Tools:**
- `list_endpoints` - Search and filter API endpoints
- `call_endpoint` - Direct API calls to any endpoint
- `get_schema` - Resolve schema references

**Category Tools (top 10):**
- `manage_services` - Ceph services operations
- `manage_maintenance` - Maintenance tasks
- `manage_s3` - S3 bucket management
- `manage_pools` - Storage pool operations
- `manage_servers` - Server management
- And more...

Each category tool supports actions like: `list`, `get`, `create`, `update`, `delete`

### Base Only Mode

Minimal setup with just 3 tools for full API access:
- `list_api_endpoints` - Discover available endpoints
- `call_api_endpoint` - Make API calls
- `get_reference_schema` - Resolve schemas

### Categories Only Mode

Simplified interface with only category tools, no base tools.

### Endpoints as Tools Mode (Legacy)

Creates 580 individual tools (one per API endpoint). Not recommended due to:
- Performance overhead
- Difficult tool discovery
- MCP client limitations

## Permission-Based Filtering

The server intelligently filters tools based on the API token's role:

1. **Automatic Role Detection**: Fetches roles via `/auth/token-info` endpoint
2. **Role-Based Access**:
   - **ADMIN role**: Full access to all categories
   - **VIEWER/other roles**: All categories except admin-only operations
   - **Invalid token**: Server will exit with error (no access)

### Category Access Control

**Admin-Only Categories:**
- `maintenance`, `servers`, `ipmi` - System management
- `config`, `hooks`, `change-requests` - Configuration changes
- `config-templates` - Template management

**All Other Categories** are accessible to VIEWER roles for read operations:
- `cluster`, `status`, `stats` - Monitoring
- `logs`, `disks`, `services` - Information viewing
- `s3`, `cephfs`, `rbds`, `pools` - Storage info
- `authentication`, `images`, `daos` - Read operations
- And all others not listed as admin-only

This role-based approach is fast and ensures users only see tools they can actually use.

## Using Local OpenAPI Spec

For offline development or testing:

```bash
# Download spec from your cluster
curl -H "Authorization: Bearer $CROIT_API_TOKEN" \
     https://your-cluster/api/swagger.json > openapi.json

# Use the local file
python mcp-croit-ceph.py --openapi-file openapi.json
```

## MCP Integration

### With Claude Desktop

Add to your Claude Desktop config:

```json
{
  "mcpServers": {
    "croit-ceph": {
      "command": "python",
      "args": ["/path/to/mcp-croit-ceph.py"],
      "env": {
        "CROIT_HOST": "https://your-cluster",
        "CROIT_API_TOKEN": "your-token"
      }
    }
  }
}
```

### With Other MCP Clients

The server implements the standard MCP protocol and works with any compatible client.

## Command Line Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--mode` | Tool generation mode | `hybrid` |
| `--openapi-file` | Local OpenAPI spec file | None (fetch from server) |
| `--no-permission-check` | Skip permission checking | False (check enabled) |
| `--max-category-tools` | Max category tools to generate | 10 |
| `--no-resolve-references` | Don't resolve $ref in spec | False (resolve enabled) |
| `--offer-whole-spec` | Include full spec in list tool | False |

## Development

### Testing Tool Count

```bash
# Check how many tools will be generated
python -c "
from mcp_croit_ceph import CroitCephServer
server = CroitCephServer(mode='hybrid')
print(f'Tool count: {len(server.mcp_tools)}')
"
```

### Debug Logging

```bash
# Enable debug logging
export LOG_LEVEL=DEBUG
python mcp-croit-ceph.py
```

## License

Apache 2.0

## Support

For issues specific to this MCP server, please open an issue in this repository.
For Croit-specific questions, contact Croit support.