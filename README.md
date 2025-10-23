# MCP Croit Ceph

MCP server that exposes the Croit Ceph REST API (and VictoriaLogs) to Model Context Protocol clients with built-in token optimization and tool generation.

---

## Use the Tool

### Client Integrations (Copy & Paste)

#### Claude Desktop
Add the server to `~/.config/Claude/claude_desktop_config.json` (adjust paths, secrets, and image tag as needed):

```json
{
  "mcpServers": {
    "mcp-croit-ceph": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i", "--net=host",
        "-e", "USE_INCLUDED_API_SPEC=1",
        "-e", "CROIT_HOST=https://your-croit-management-node:8080",
        "-e", "CROIT_API_TOKEN=REPLACE_WITH_TOKEN",
        "croit/mcp-croit-ceph:latest"
      ]
    }
  }
}
```

#### Claude Code
Claude Code reads MCP servers from `~/.config/Claude/claude_code_config.json`. Reuse the same command/args block:

```json
{
  "mcpServers": {
    "mcp-croit-ceph": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i", "--net=host",
        "-e", "USE_INCLUDED_API_SPEC=1",
        "-e", "CROIT_HOST=https://your-croit-management-node:8080",
        "-e", "CROIT_API_TOKEN=REPLACE_WITH_TOKEN",
        "croit/mcp-croit-ceph:latest"
      ]
    }
  }
}
```

#### Codex CLI
To use the server inside the Codex CLI, add it to `~/.config/codex/mcp_servers.json`:

```json
{
  "mcpServers": {
    "croit-ceph": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i", "--net=host",
        "-e", "USE_INCLUDED_API_SPEC=1",
        "-e", "CROIT_HOST=https://your-croit-management-node:8080",
        "-e", "CROIT_API_TOKEN=REPLACE_WITH_TOKEN",
        "croit/mcp-croit-ceph:latest"
      ]
    }
  }
}
```

#### Gemini Advanced Code Assist
Gemini’s MCP bridge uses `~/.config/google/gemini/mcp_servers.json`. Register the server with the same command:

```json
{
  "servers": {
    "croit-ceph": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i", "--net=host",
        "-e", "USE_INCLUDED_API_SPEC=1",
        "-e", "CROIT_HOST=https://your-croit-management-node:8080",
        "-e", "CROIT_API_TOKEN=REPLACE_WITH_TOKEN",
        "croit/mcp-croit-ceph:latest"
      ]
    }
  }
}
```

Configuration file locations can vary between releases—if your client cannot see the server, check its MCP documentation and point it at the same Docker (or Python) command shown above. Remove `USE_INCLUDED_API_SPEC=1` if you prefer the server to fetch the live spec from `CROIT_HOST`, or provide your own JSON via `OPENAPI_FILE=/path/to/spec.json`.

#### What You Need
- A reachable Croit Ceph cluster (`CROIT_HOST`)
- An API token with suitable permissions (`CROIT_API_TOKEN`)
- Optional: a cached OpenAPI document (`openapi.json`) for offline or repeatable startup

The server reads configuration from environment variables first and falls back to `/config/config.json`:

```json
{
  "host": "https://your-croit-cluster.example:8080",
  "api_token": "xxxxxx"
}
```

By default the MCP server downloads the latest OpenAPI spec from `CROIT_HOST`. Set `USE_INCLUDED_API_SPEC=1` (or pass `--use-included-api-spec`) to load the enhanced spec bundled with this project instead.

### Tooling at Runtime
- **Hybrid mode (default):** ~13 tools combining discovery (`list_endpoints`, `call_endpoint`, `get_schema`) with curated categories (services, pools, maintenance, etc.).
- **Base only:** Minimal surface using the three base tools.
- **Categories only:** Just the curated categories for a guided experience.
- **Endpoints as tools:** One MCP tool per REST endpoint (legacy, heavy).

Token optimization features automatically add pagination defaults, truncate large payloads with metadata, and support server-side filtering parameters such as `_filter_status`, `_filter__text`, numeric comparisons, and regex matching.

#### Log Intelligence
If `croit_log_tools.py` is available, `croit_log_search` and `croit_log_check` expose VictoriaLogs directly with:
- Intent parsing for common Ceph trouble patterns
- Direct JSON query support (`_and`, `_or`, `_regex`, `_exists`, ...)
- Smart summaries: priority breakdowns, critical event extraction, server activity, recommendations

---

## Develop the Tool

### Repository Layout
- `mcp-croit-ceph.py` – main server, tool generation, configuration loading.
- `token_optimizer.py` – applies default limits, truncation, field filtering, and summaries.
- `croit_log_tools.py` – VictoriaLogs WebSocket client, intent parser, templates, response summariser.
- `ARCHITECTURE.md` – system design deep dive.
- `Dockerfile` / `build.sh` – container build assets.

### Local Development Workflow
```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

export CROIT_HOST="https://dev-cluster"
export CROIT_API_TOKEN="dev-token"
python mcp-croit-ceph.py --openapi-file openapi.json --no-permission-check
```

- Helpful switches:
  - `--mode {hybrid,base_only,categories_only,endpoints_as_tools}`
  - `--openapi-file PATH` to reuse a local spec
  - `--use-included-api-spec` to force the bundled spec without setting env vars
  - `--no-permission-check` to skip role discovery when testing
  - `--max-category-tools N` to cap category fan-out
- Toggle debug output with `LOG_LEVEL=DEBUG`.
- To test against recorded specs, drop them in `openapi.json` or mount via Docker.

### Standalone Docker (local testing)
```bash
docker run --rm -it \
  -e CROIT_HOST="https://your-cluster" \
  -e CROIT_API_TOKEN="your-token" \
  croit/mcp-croit-ceph:latest
```

Add `-e USE_INCLUDED_API_SPEC=1` if you want to exercise the bundled spec without touching the cluster.

#### Local Spec + Host Network example
Ideal when you want the enhanced spec shipped with the container and need to reach services on localhost:
```bash
docker run --rm -it \
  --net=host \
  -e USE_INCLUDED_API_SPEC=1 \
  -e CROIT_HOST="https://your-croit-management-node:8080" \
  -e CROIT_API_TOKEN="REPLACE_WITH_TOKEN" \
  croit/mcp-croit-ceph:latest
```

### Testing & Tooling
- Targeted scripts: `python test_timestamp_fix.py`, `python test_actual_mcp.py`.
- Measure tool counts quickly:
  ```bash
  for mode in hybrid base_only categories_only; do
    python mcp-croit-ceph.py --mode "$mode" --openapi-file openapi.json --no-permission-check \
      2>&1 | grep -o 'Generated [0-9]* tools'
  done
  ```
- Docker build for release:
  ```bash
  docker build -t mcp-croit-ceph:latest .
  docker tag mcp-croit-ceph:latest croit/mcp-croit-ceph
  ```

### Contributing Tips
- Always work in a virtual environment; system Python is managed.
- Keep changes ASCII unless a file already uses other encodings.
- Architecture and x-llm-hints behaviour are documented in `ARCHITECTURE.md`—skim it before large changes.
- When adding endpoints or categories, consider performance impact (token optimizer limits, log tools availability).

---

## Reference
- License: Apache 2.0 (`LICENSE`)
- MCP registry metadata: `server.json`
- Need implementation details? Start with `ARCHITECTURE.md`.
- Support: file an issue in this repository or reach out to Croit support for cluster-specific questions.
