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
- `CONFIG_PATH`: Path to config.json
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
