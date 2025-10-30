# MCP Croit Ceph

An MCP (Model Context Protocol) server for interacting with Croit Ceph clusters through their REST API.

## Features

### Automatic Token Optimization

The MCP server automatically optimizes responses to reduce token consumption:
- **Auto-limits**: Adds default limits (10-100 items) to list operations
- **Smart truncation**: Large responses automatically truncated with metadata
- **Optimization hints**: Tool descriptions include token-saving tips
- **Response metadata**: Truncated responses include info on how to get more data

Example: Instead of 500 services (50,000 tokens), you get 25 services + metadata (2,500 tokens)

### Built-in Filtering (grep-like search)

Filter API responses locally without multiple calls:
- **Field filtering**: `_filter_status='error'` - exact match
- **Regex patterns**: `_filter_name='~ceph.*'` - pattern matching
- **Numeric comparisons**: `_filter_size='>1000'` - greater than
- **Text search**: `_filter__text='timeout'` - search all text fields
- **Field existence**: `_filter__has='error_message'` - has field
- **Multiple values**: `_filter_status=['error','warning']` - OR logic

Example: Find errors in 500 services with one call:
```
_filter_status='error' → Returns only 5 error services (99% token savings)
```

### Intelligent Tool Organization

The MCP server provides a streamlined set of tools for efficient cluster management:
- **Base tools** for direct API access
- **Category tools** for common operations (services, maintenance, s3, pools, etc.)
- **Advanced log search** with VictoriaLogs integration

### Dynamic Features

- **Automatic API Discovery**: Fetches OpenAPI spec from your Croit cluster
- **Permission-Based Filtering**: Role-based tool filtering (ADMIN vs VIEWER)
- **Full x-llm-hints Support**: 575+ endpoints with AI optimization hints
- **Local OpenAPI Support**: Use a local OpenAPI spec file for testing/development
- **Schema Resolution**: Handles `$ref` references automatically

### Advanced x-llm-hints Integration

The MCP server fully integrates Croit's x-llm-hints into tool descriptions for optimal LLM guidance:

**What x-llm-hints provide:**
- **Purpose**: Clear description of what each endpoint does
- **Usage examples**: Common use cases and workflow guidance
- **Failure modes**: Expected errors and how to handle them
- **Rate limits**: API throttling information for efficient usage
- **Retry strategies**: How to handle transient failures
- **Poll intervals**: Recommended refresh rates for live data
- **Cache hints**: Response caching strategies
- **Related endpoints**: Cross-references for complex workflows

**Examples of integrated hints:**
```
manage_cluster tool:
Purpose: Bootstrap a brand-new Ceph cluster using the selected MON disk and IP address.

Common usage:
• Invoke immediately after fetching candidates from GET /cluster/create/mons
• Monitor the returned ManagedTask via /tasks/{id} until bootstrap completes

Failure modes:
• 400: Validate disk/server eligibility via GET /cluster/create/mons
• 409: If concurrent bootstrap is in progress, wait for existing task

Rate limits: 60/300s, 30/300s
Retry strategy: manual_retry, exponential_backoff
```

**Benefits for LLMs:**
- **Context-aware operations**: LLMs understand when and how to use each tool
- **Error handling**: Proactive guidance on handling API errors
- **Performance optimization**: Built-in rate limiting and caching awareness
- **Workflow intelligence**: Understanding of multi-step operations

## Installation

⚠️ **IMPORTANT**: This project requires a virtual environment due to system-managed Python environments.

```bash
# Clone the repository
git clone https://github.com/croit/mcp-croit-ceph.git
cd mcp-croit-ceph

# Create and activate virtual environment (REQUIRED)
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies in virtual environment
pip install -r requirements.txt
```

**Note**: Always activate the virtual environment (`source venv/bin/activate`) before running any Python commands or tests.

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

### Basic Usage

```bash
# Activate virtual environment first (REQUIRED)
source venv/bin/activate

# Run with default configuration
python mcp-croit-ceph.py
```

### Advanced Options

```bash
# Activate virtual environment first (REQUIRED)
source venv/bin/activate

# Use local OpenAPI spec file
python mcp-croit-ceph.py --openapi-file openapi.json

# Skip permission checking (faster startup)
python mcp-croit-ceph.py --no-permission-check

# Customize category tool limits
python mcp-croit-ceph.py --max-category-tools 5
```

## Available Tools

The MCP server provides a comprehensive set of tools:

**Base Tools:**
- `list_endpoints` - Search and filter API endpoints with smart prioritization
- `call_endpoint` - Direct API calls to any endpoint with token optimization
- `get_schema` - Resolve schema references

**Category Tools:**
- `manage_services` - Ceph services operations
- `manage_maintenance` - Maintenance tasks
- `manage_s3` - S3 bucket management
- `manage_pools` - Storage pool operations
- `manage_servers` - Server management
- And more dynamically generated based on your cluster's API

**Log Search Tools:**
- `croit_log_search` - Advanced log analysis with VictoriaLogs
- `croit_log_check` - Instant log condition checking

Each category tool supports actions like: `list`, `get`, `create`, `update`, `delete`

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

### Docker Integration for LLMs

For integration with LLM systems, use the Docker container with local OpenAPI spec:

```json
{
  "mcpServers": {
    "mcp-croit-ceph": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "-v",
        "/path/to/openapi.json:/config/openapi.json:ro",
        "-e",
        "OPENAPI_FILE=/config/openapi.json",
        "-e",
        "CROIT_HOST=http://your-cluster:8080",
        "-e",
        "CROIT_API_TOKEN=your-api-token",
        "mcp-croit-ceph:latest"
      ]
    }
  }
}
```

This approach:
- Uses a local OpenAPI spec for faster startup
- Avoids network calls during initialization
- Provides consistent tool definitions
- Ideal for production deployments

### With Other MCP Clients

The server implements the standard MCP protocol and works with any compatible client.

## Command Line Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--openapi-file` | Local OpenAPI spec file | None (fetch from server) |
| `--no-permission-check` | Skip permission checking | False (check enabled) |
| `--max-category-tools` | Max category tools to generate | 10 |
| `--no-resolve-references` | Don't resolve $ref in spec | False (resolve enabled) |

## Docker Usage

### Build and Run with Docker

```bash
# Build the Docker image
docker build -t mcp-croit-ceph .

# Run with environment variables
docker run -it --rm \
  -e CROIT_HOST="https://your-cluster" \
  -e CROIT_API_TOKEN="your-token" \
  mcp-croit-ceph

# Run with local OpenAPI spec (for testing)
docker run -it --rm \
  -v $(pwd)/openapi.json:/config/openapi.json:ro \
  -e CROIT_HOST="http://dummy" \
  -e CROIT_API_TOKEN="dummy" \
  mcp-croit-ceph \
  --openapi-file /config/openapi.json --no-permission-check
```

### Docker Compose

```yaml
version: '3.8'
services:
  mcp-croit-ceph:
    image: mcp-croit-ceph:latest
    environment:
      CROIT_HOST: "${CROIT_HOST}"
      CROIT_API_TOKEN: "${CROIT_API_TOKEN}"
    volumes:
      # Optional: Use local OpenAPI spec
      - ./openapi.json:/config/openapi.json:ro
```

## Development

⚠️ **Remember**: Always activate the virtual environment before development work:
```bash
source venv/bin/activate
```


### Debug Logging

```bash
# Activate virtual environment first
source venv/bin/activate

# Enable debug logging
export LOG_LEVEL=DEBUG
python mcp-croit-ceph.py
```

### Testing with Local OpenAPI Spec

```bash
# Activate virtual environment first
source venv/bin/activate

# Use the test script
./test-local.sh

# Or manually test
python mcp-croit-ceph.py --openapi-file openapi.json --no-permission-check
```

### Running Tests

```bash
# Activate virtual environment first
source venv/bin/activate

# Run timestamp fix test
python test_timestamp_fix.py

# Run other tests (ensure dependencies are installed in venv)
python test_actual_mcp.py
```

## License

Apache 2.0

## Support

For issues specific to this MCP server, please open an issue in this repository.
For Croit-specific questions, contact Croit support.