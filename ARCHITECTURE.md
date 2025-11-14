# MCP Croit Ceph - System Architecture

## Documentation Structure

**Main Overview**: This file provides the complete system architecture.
**Detailed Components**: The `docs/` folder contains deep-dives into major components and workflows.

**For LLMs**: Read `docs/ARCHITECTURE.<topic>.md` files for implementation details.

## System Overview

MCP server providing LLM-driven access to Croit Ceph cluster management via dynamically generated tools from OpenAPI specifications with advanced VictoriaLogs integration.

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ LLM Client  │────▶│   MCP Server     │────▶│ Croit Cluster   │
│  (Claude)   │◀────│ (This System)    │◀────│ API + Logs      │
└─────────────┘     └──────────────────┘     └─────────────────┘
                            │
                    ┌───────┴────────┐
                    │                │
            ┌───────▼──────┐  ┌──────▼───────┐
            │  API Tools   │  │  Log Search  │
            │  Generation  │  │  System      │
            └──────────────┘  └──────────────┘
```

**Key Metrics**: 3 modules (5,296 lines), 580+ API endpoints, 3 operational modes

## Architecture Principles

- **SoC**: Clear module boundaries (MCP protocol, API handling, log search)
- **DDD**: Category-based organization mirrors Ceph operational domains
- **DRY**: Shared TokenOptimizer, reusable schema resolution
- **KISS**: Direct VictoriaLogs queries without translation layers

## Core Components

### 1. MCP Server Core
Central MCP protocol implementation coordinating all subsystems.
📄 [docs/ARCHITECTURE.mcp-server-core.md](docs/ARCHITECTURE.mcp-server-core.md)

**Responsibilities**: Handler registration, tool invocation routing, session lifecycle, mode-based selection

### 2. Tool Generation Engine
Dynamic tool creation from OpenAPI specs with x-llm-hints integration.
📄 [docs/ARCHITECTURE.tool-generation-engine.md](docs/ARCHITECTURE.tool-generation-engine.md)

**Responsibilities**: OpenAPI parsing, 3-mode generation (hybrid/base/categories), category grouping, x-llm-hints integration

### 3. Token Optimizer
Performance-critical module reducing LLM token consumption by 90%+.
📄 [docs/ARCHITECTURE.token-optimizer.md](docs/ARCHITECTURE.token-optimizer.md)

**Responsibilities**: Response truncation, grep-like filtering (regex, numeric, field existence), field selection, default pagination

### 4. Log Search System
Advanced log analysis with VictoriaLogs integration (8 classes, 2,661 lines).
📄 [docs/ARCHITECTURE.log-search-system.md](docs/ARCHITECTURE.log-search-system.md)

**Responsibilities**: Intent parsing, direct JSON queries, WebSocket streaming, HTTP fallback, summarization, critical event extraction

## Key Workflows

### Server Initialization
Multi-stage bootstrap: config → OpenAPI fetch → schema resolution → tool generation → MCP registration.
📄 [docs/ARCHITECTURE.server-initialization-flow.md](docs/ARCHITECTURE.server-initialization-flow.md)

**Duration**: 2-7s (or 1-4s with local spec)

### API Request Execution
Complete lifecycle: invocation → validation → optimization → HTTP request → filtering → response.
📄 [docs/ARCHITECTURE.api-request-execution.md](docs/ARCHITECTURE.api-request-execution.md)

**Duration**: 100-2000ms per request

### Log Search Execution
Dual-path execution: intent parsing → query building → WebSocket/HTTP → summarization.
📄 [docs/ARCHITECTURE.log-search-execution.md](docs/ARCHITECTURE.log-search-execution.md)

**Duration**: 500ms - 10s depending on scope

## Module Structure

```
mcp-croit-ceph.py (2,212 lines)
├── CroitCephServer class
│   ├── Configuration & OpenAPI (7 methods)
│   ├── Schema resolution (3 methods)
│   ├── API structure analysis (3 methods)
│   ├── Tool generation (6 methods)
│   └── Tool handlers (6 methods)
└── main() entrypoint

token_optimizer.py (423 lines)
└── TokenOptimizer class (12 methods)

croit_log_tools.py (2,661 lines)
├── LogSearchIntentParser
├── LogsQLBuilder
├── CroitLogSearchClient (35+ methods)
├── CephServiceTranslator
├── CephDebugTemplates
├── ServerIDDetector
├── LogTransportAnalyzer
├── LogSummaryEngine
└── Handler functions (3)
```

## Operational Modes

### Hybrid (Default)
13 tools: 3 base discovery + 10 category-specific. Optimal balance.

### Base Only
3 tools: list/call/schema. Minimal footprint, maximum control.

### Categories Only
10-15 tools: One per major category. Guided interface.

## Data Flow

**API Call Flow**:
```
LLM Request → Tool Invocation → Schema Validation → Token Optimization →
HTTP Request → Croit API → Response Filtering → Token Optimization → LLM Response
```

**Log Search Flow**:
```
LLM Query → Intent Parsing → LogsQL Building → WebSocket/HTTP →
VictoriaLogs → Stream Processing → Summarization → LLM Response
```

**Tool Generation Flow**:
```
Server Init → OpenAPI Fetch → Schema Resolution → Category Analysis →
Permission Filtering → Mode Selection → Tool Creation → MCP Registration
```

## Performance Characteristics

**Token Optimization Impact**:
- Default pagination: 90%+ reduction on list operations
- Response truncation: 25-100 items (configurable)
- Field filtering: 50-70% reduction
- Hint suppression: 30-40% reduction on repeated calls

**Caching**:
- OpenAPI spec: In-memory, full lifecycle
- Log search: 5-minute cache per query hash

**Connection Pooling**:
- HTTP: aiohttp.ClientSession (persistent)
- WebSocket: Per-request (no pooling)

## Security

**Authentication**: Bearer token (Authorization header), binary WebSocket auth
**Permission Enforcement**: Role-based tool filtering (ADMIN vs VIEWER), category-level access
**Input Validation**: OpenAPI schema validation, query sanitization, regex pattern validation

## Configuration

**Required Environment Variables**:
- `CROIT_HOST`: Cluster URL
- `CROIT_API_TOKEN`: API token

**Optional**:
- `USE_INCLUDED_API_SPEC`: Use bundled spec (1/true/yes/on)
- `LOG_LEVEL`: Logging verbosity

**CLI Options**:
```bash
python mcp-croit-ceph.py --mode hybrid               # Default
python mcp-croit-ceph.py --openapi-file spec.json    # Local spec
python mcp-croit-ceph.py --no-permission-check       # Skip role check
python mcp-croit-ceph.py --max-category-tools 5      # Limit categories
```

## Design Patterns

**Strategy Pattern**: Tool modes (hybrid/base_only/categories_only)
**Builder Pattern**: LogsQL query construction, tool definition building
**Adapter Pattern**: OpenAPI to MCP tool adaptation
**Template Method**: Common API call structure with customization points
**Factory Pattern**: Mode-specific tool creation

## Key Features

**Dynamic API Discovery**: Fetches OpenAPI from cluster or uses bundled spec
**x-llm-hints Integration**: 575+ endpoints with AI optimization hints (99.1% coverage)
**Permission-Based Filtering**: ADMIN vs VIEWER role enforcement
**grep-like Filtering**: `_filter_status="error"`, `_filter_name="~ceph.*"`, numeric comparisons
**Natural Language Log Search**: "Find OSD errors in last hour" → structured query
**Pre-built Debug Templates**: 10 common Ceph troubleshooting scenarios
**Server Auto-Discovery**: Automatic server ID detection from logs
**Critical Event Extraction**: Intelligent log summarization with recommendations

## Extension Points

1. **New Tool Modes**: Add to mode validation and create preparation method
2. **Additional Categories**: Extend category mapping in `_analyze_api_structure`
3. **Custom Optimizations**: Add methods to TokenOptimizer
4. **Log Search Patterns**: Extend PATTERNS dict in LogSearchIntentParser
5. **Debug Templates**: Add to CephDebugTemplates.TEMPLATES

## Dependencies

**External Libraries**:
- `mcp`: Model Context Protocol server
- `aiohttp`: Async HTTP client
- `websockets`: WebSocket client for logs
- `requests`: Sync HTTP for OpenAPI fetching

**Internal Coupling**:
- mcp-croit-ceph.py imports: token_optimizer, croit_log_tools (optional)
- Other modules: standalone, no internal imports

## Troubleshooting

**Slow Startup**: Use local/bundled spec, disable reference resolution, reduce max_category_tools
**Missing Tools**: Verify mode selection, check permissions, confirm log tools installed
**WebSocket Failures**: Falls back to HTTP export automatically
**Token Exhaustion**: Enable optimization, use filters, reduce limits

## Maintenance

**When to Update Docs**:
- New classes/functions → Update relevant component doc
- Workflow changes → Update process documentation
- New dependencies → Update this file

**Documentation Review**: Quarterly for processes, on major releases for full audit

## Related Resources

- **User Guide**: README.md
- **AI Assistant Instructions**: CLAUDE.md
- **Build**: Dockerfile, build.sh
- **CI/CD**: .gitlab-ci.yml, .github/workflows/

## Version

**Current Architecture**: v0.4.x
**Last Revision**: 2024-10-30 (Streamlined documentation)
**Total Documentation**: 8 files (main + 7 detailed docs)


---

## Technical Details for Developers

This section contains technical information previously in README.md, aimed at developers working on the codebase.

### Development Setup

**Virtual Environment (Required)**

This project requires a virtual environment due to system-managed Python:

```bash
# Create virtual environment
python3 -m venv venv

# Activate (Linux/Mac)
source venv/bin/activate

# Activate (Windows)
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install aiohttp websockets  # For log search
```

**Pre-Commit Hook**

⚠️ **CRITICAL**: Run black formatter before every commit!

```bash
# GitLab CI will fail if code is not formatted
source venv/bin/activate
black --check .  # Check
black .          # Fix

# Quick fix for CI failures
black croit_log_tools.py mcp-croit-ceph.py token_optimizer.py
git add -u
git commit -m "fix: Apply black formatting"
git push
```

### Running Tests

```bash
# Always activate venv first
source venv/bin/activate

# Test timestamp calculation fix
python test_timestamp_fix.py

# Test MCP functionality
CROIT_API_TOKEN="your-token" python test_actual_mcp.py

# Test token optimization
python test_token_optimization.py
python test_field_projection.py

# Basic MCP server test
python mcp-croit-ceph.py --openapi-file openapi.json --no-permission-check
```

### Command Line Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--openapi-file FILE` | Use local OpenAPI spec | Fetch from server |
| `--no-permission-check` | Skip role-based filtering | False (check enabled) |
| `--max-category-tools N` | Max category tools | 10 |
| `--no-resolve-references` | Don't resolve $ref | False (resolve) |
| `--mode MODE` | Tool mode (hybrid/base/categories) | hybrid |

### Debug Logging

```bash
source venv/bin/activate
export LOG_LEVEL=DEBUG
python mcp-croit-ceph.py
```

### Docker Development

**Build:**
```bash
docker build -t mcp-croit-ceph .
```

**Run with local spec:**
```bash
docker run -it --rm \
  -v $(pwd)/openapi.json:/config/openapi.json:ro \
  -e CROIT_HOST="http://dummy" \
  -e CROIT_API_TOKEN="dummy" \
  mcp-croit-ceph \
  --openapi-file /config/openapi.json --no-permission-check
```

**Docker Compose:**
```yaml
version: '3.8'
services:
  mcp-croit-ceph:
    image: mcp-croit-ceph:latest
    environment:
      CROIT_HOST: "${CROIT_HOST}"
      CROIT_API_TOKEN: "${CROIT_API_TOKEN}"
    volumes:
      - ./openapi.json:/config/openapi.json:ro
```

### OpenAPI Spec Management

⚠️ **DO NOT EDIT openapi.json DIRECTLY**

The `openapi.json` file is auto-generated from the Croit API backend. To update x-llm-hints, changes must be made in the Croit API source code.

**Current Status (v0.4.0):**
- **580** total API endpoints
- **575** endpoints with x-llm-hints (99.1% coverage)
- **5** endpoints missing x-llm-hints

**Download latest spec:**
```bash
curl -H "Authorization: Bearer $CROIT_API_TOKEN" \
     https://your-cluster/api/swagger.json > openapi.json
```

### Environment Variables

**Required:**
- `CROIT_HOST` - Cluster URL
- `CROIT_API_TOKEN` - API token

**Optional:**
- `USE_INCLUDED_API_SPEC` - Use bundled spec (1/true/yes/on)
- `LOG_LEVEL` - Logging verbosity (DEBUG/INFO/WARNING/ERROR)

### Module Structure

```
mcp-croit-ceph.py (2,470 lines)
├── CroitCephServer class
│   ├── Configuration & OpenAPI (7 methods)
│   ├── Schema resolution (3 methods)
│   ├── API structure analysis (3 methods)
│   ├── Tool generation (6 methods)
│   └── Tool handlers (6 methods)
└── main() entrypoint

token_optimizer.py (1,120 lines)
├── ResponseCache class
├── TokenOptimizer class (20+ methods)
└── Integration functions (5)

croit_log_tools.py (2,661 lines)
├── LogSearchIntentParser
├── LogsQLBuilder
├── CroitLogSearchClient (35+ methods)
├── CephServiceTranslator
├── CephDebugTemplates
├── ServerIDDetector
├── LogTransportAnalyzer
├── LogSummaryEngine
└── Handler functions (3)

constants.py (NEW)
└── All configuration constants
```

### Operational Modes

**Hybrid (Default):**
- 13 tools: 3 base + 10 category-specific
- Optimal balance of simplicity and power

**Base Only:**
- 3 tools: list/call/schema
- Minimal footprint, maximum control

**Categories Only:**
- 10-15 tools: One per major category
- Guided interface

**Usage:**
```bash
python mcp-croit-ceph.py --mode hybrid      # Default
python mcp-croit-ceph.py --mode base_only
python mcp-croit-ceph.py --mode categories_only
```

### Performance Tuning

**Feature Flags:**
```bash
# Disable DAOS endpoints (saves ~54 endpoints, 9.3%)
--enable-daos=false

# Disable specialty features (saves ~30 endpoints, 5.2%)
--disable-specialty-features

# Maximum reduction (~84 endpoints, 14.5%)
--disable-specialty-features
```

**Intent-based Filtering:**
```python
# Only GET operations
list_endpoints(search="pool", intent="read")

# Only POST/PUT/PATCH
list_endpoints(search="rbd", intent="write")

# Only DELETE
list_endpoints(search="osd", intent="manage")
```

**Token Savings Examples:**
```
Standard pool search: 81 endpoints
+ intent="read": 33 endpoints (59% reduction)
+ intent="write": 36 endpoints (56% reduction)
+ intent="manage": 12 endpoints (85% reduction)
```

### Common Development Patterns

```bash
# Start development session
source venv/bin/activate
export LOG_LEVEL=DEBUG
export CROIT_API_TOKEN="your-token"

# Run tests
python test_timestamp_fix.py
python test_actual_mcp.py

# Check code
black --check .
python -m py_compile *.py
```

### Troubleshooting

**Slow Startup:**
- Use local/bundled OpenAPI spec
- Disable reference resolution
- Reduce `max_category_tools`

**Missing Tools:**
- Verify mode selection
- Check permissions
- Confirm log tools installed

**WebSocket Failures:**
- Automatically falls back to HTTP
- Check VictoriaLogs service

**Token Exhaustion:**
- Enable optimization
- Use field selection
- Apply filters
- Reduce limits



---

## Project Structure

The codebase follows a clean, modular structure for better maintainability:

```
mcp-croit-ceph/
├── mcp-croit-ceph.py          # Entry point (27 lines)
│
├── src/                        # Source modules
│   ├── config/                 # Configuration
│   │   └── constants.py        # All magic numbers centralized
│   ├── core/                   # Core MCP server logic
│   │   └── mcp_server.py       # CroitCephServer class
│   ├── optimization/           # Token optimization
│   │   └── token_optimizer.py  # TokenOptimizer + caching
│   └── logs/                   # Log search functionality
│       └── croit_log_tools.py  # VictoriaLogs integration
│
├── tests/                      # Test files
│   ├── test_token_optimization.py
│   └── test_field_projection.py
│
├── docs/                       # Documentation
│   ├── ARCHITECTURE.*.md       # Component documentation
│   └── TOKEN_OPTIMIZATION.md
│
├── README.md                   # User-facing documentation
├── ARCHITECTURE.md             # This file
├── CLAUDE.md                   # AI assistant instructions
├── Dockerfile                  # Production container
└── requirements.txt            # Python dependencies
```

### Import Structure

```python
# Entry point (mcp-croit-ceph.py)
from src.core.mcp_server import main

# Core server (src/core/mcp_server.py)
from src.config.constants import MAX_SCHEMA_RESOLUTION_DEPTH
from src.optimization.token_optimizer import TokenOptimizer
from src.logs.croit_log_tools import handle_log_search

# Tests (tests/*.py)
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from src.optimization.token_optimizer import optimize_api_response
```

### Design Benefits

1. **Separation of Concerns**: Each module has a single responsibility
2. **Easy Navigation**: Find code by functional area (config, core, optimization, logs)
3. **Better Testing**: Tests isolated in tests/ directory
4. **IDE Support**: Clear module structure enables better autocomplete
5. **Scalability**: Easy to add new modules (e.g., src/utils/)

