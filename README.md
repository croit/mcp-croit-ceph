# MCP Croit Ceph

> AI-powered management for Croit Ceph clusters via the Model Context Protocol (MCP)

Connect your AI assistant (like Claude) directly to your Croit Ceph cluster for intelligent cluster management, troubleshooting, and monitoring.

## What is this?

An MCP server that gives AI assistants access to your Croit Ceph cluster's REST API. Ask your AI to:
- "Show me all pools with errors"
- "List OSDs on server node-5"
- "Search logs for slow requests in the last hour"
- "What's the cluster health status?"

The AI can then interact with your cluster through natural language.

## Key Features

### 🚀 Smart & Efficient
- **Automatic token optimization** - Responses optimized to save 80-95% on AI token costs
- **Field selection** - Request only the data you need (e.g., just id + name)
- **Built-in filtering** - grep-like search without multiple API calls
- **Intelligent summaries** - Large datasets get smart summaries with drill-down capability

### 🔍 Advanced Log Search
- Native VictoriaLogs integration for powerful log analysis
- Natural language queries: "Find OSD failures in the last 24 hours"
- Pattern detection and anomaly identification
- Pre-built debug templates for common issues

### 🛡️ Production Ready
- Role-based access control (ADMIN vs VIEWER)
- Automatic API discovery from your cluster
- Docker support with included OpenAPI spec
- Comprehensive error handling

## Quick Start

### Using Docker (Recommended)

```bash
docker run --rm -i \
  -e CROIT_HOST="https://your-cluster.com" \
  -e CROIT_API_TOKEN="your-api-token" \
  croit/mcp-croit-ceph:latest
```

### With Claude Desktop

Add to `~/.config/claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "croit-ceph": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-e", "CROIT_HOST=https://your-cluster.com",
        "-e", "CROIT_API_TOKEN=your-token",
        "croit/mcp-croit-ceph:latest"
      ]
    }
  }
}
```

Restart Claude Desktop, and you're ready to manage your Ceph cluster with AI!

## Configuration

Only two environment variables required:

```bash
CROIT_HOST="https://your-cluster.com"      # Your Croit cluster URL
CROIT_API_TOKEN="your-api-token"           # API token from Croit
```

### Getting an API Token

1. Log into your Croit cluster web interface
2. Go to **Settings** → **API Tokens**
3. Create a new token with appropriate permissions
4. Copy the token and use it in your configuration

## Example AI Conversations

**Check cluster health:**
```
You: "What's the current cluster status?"
AI: Calls list_endpoints → Finds status endpoint → Returns health summary
```

**Find problems:**
```
You: "Show me all pools with errors"
AI: Calls /pools with fields=["id","name","status"] and filter for errors
    Returns only the 3 pools with issues (instead of all 100 pools)
```

**Debug issues:**
```
You: "Search logs for OSD failures in the last hour"
AI: Uses croit_log_search with smart query parsing
    Returns summary + drill-down capability for details
```

**Capacity planning:**
```
You: "Which pools are over 80% full?"
AI: Gets pools → Filters by usage → Returns list with recommendations
```

## Features in Detail

### Token Optimization

The server automatically reduces AI token consumption:

| Without Optimization | With Optimization | Savings |
|---------------------|-------------------|---------|
| 100 pools, all fields → 4,000 tokens | 100 pools, id+name → 300 tokens | **92%** |
| 500 OSDs, full data → 15,000 tokens | Smart summary → 1,000 tokens | **93%** |

**How it works:**
1. **Field Selection**: Request only needed fields
2. **Smart Summaries**: Large datasets get summaries with drill-down
3. **Caching**: Repeated requests use cached data
4. **Auto-limiting**: Sensible defaults prevent token explosions

### Available Tools

The AI has access to these tools:

**Core Tools:**
- `list_endpoints` - Discover available API endpoints
- `call_endpoint` - Make API calls with optimization
- `search_last_result` - Drill down into large responses

**Category Tools** (auto-generated):
- `manage_services` - Ceph services
- `manage_pools` - Storage pools
- `manage_servers` - Cluster servers
- `manage_s3` - S3 buckets
- And more...

**Log Search:**
- `croit_log_search` - Advanced log analysis
- `croit_log_check` - Quick log condition checks

## Advanced Usage

### Local Development

```bash
# Clone repository
git clone https://github.com/croit/mcp-croit-ceph.git
cd mcp-croit-ceph

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run directly
export CROIT_HOST="https://your-cluster.com"
export CROIT_API_TOKEN="your-token"
python mcp-croit-ceph.py
```

### Using Local OpenAPI Spec

For faster startup or offline development:

```bash
# Download spec from your cluster
curl -H "Authorization: Bearer $CROIT_API_TOKEN" \
     https://your-cluster/api/swagger.json > openapi.json

# Use local spec
python mcp-croit-ceph.py --openapi-file openapi.json
```

### Command Line Options

```bash
python mcp-croit-ceph.py \
  --openapi-file openapi.json \      # Use local OpenAPI spec
  --no-permission-check \            # Skip role check (faster)
  --max-category-tools 5             # Limit category tools
```

## Permissions & Security

The server respects your API token's role:

- **ADMIN**: Full access to all operations
- **VIEWER**: Read-only access (no create/delete/update)
- **Invalid token**: Server exits with error

Admin-only categories: `maintenance`, `servers`, `config`, `hooks`

## Troubleshooting

**Token not working:**
- Verify token in Croit web interface
- Check token hasn't expired
- Ensure token has correct permissions

**Connection issues:**
- Verify `CROIT_HOST` is correct (include https://)
- Check network connectivity to cluster
- Verify firewall allows connection

**No tools showing:**
- Check Docker logs for errors
- Verify OpenAPI spec is valid
- Try `--no-permission-check` to test

**Enable debug logging:**
```bash
export LOG_LEVEL=DEBUG
python mcp-croit-ceph.py
```

## Documentation

- **[Architecture](ARCHITECTURE.md)** - Technical architecture and design
- **[Token Optimization](docs/TOKEN_OPTIMIZATION.md)** - How optimization works
- **[Claude Integration](CLAUDE.md)** - Tips for using with Claude

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run `black` formatter on Python files
5. Submit a pull request

## License

See [LICENSE](LICENSE) for details

## Support

- **Issues**: [GitHub Issues](https://github.com/croit/mcp-croit-ceph/issues)
- **Croit Support**: For cluster-specific questions
- **MCP Protocol**: [Model Context Protocol Documentation](https://modelcontextprotocol.io)

---

Made with ❤️  for the Ceph community
