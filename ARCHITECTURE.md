# MCP Croit Ceph - System Architecture

## Documentation Structure

This file provides a high-level overview of the system architecture. Detailed component documentation is located in the **docs/** subfolder.

**For LLMs**: When investigating specific components, workflows, or design patterns, read the corresponding `docs/ARCHITECTURE.<topic>.md` files referenced throughout this document.

## System Overview

The MCP Croit Ceph server is a Model Context Protocol (MCP) implementation that provides LLM-driven access to Croit Ceph cluster management. The system dynamically generates tools from OpenAPI specifications and implements advanced log search capabilities via VictoriaLogs.

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

**Key Metrics:**
- 3 Python modules (5,296 total lines)
- 580+ API endpoints dynamically discovered
- 23 architecture components
- 3 operational modes (hybrid/base_only/categories_only)

## Architectural Principles

This system follows:
- **SoC (Separation of Concerns)**: Clear module boundaries between MCP protocol, API handling, log search
- **DDD (Domain-Driven Design)**: Category-based organization mirrors Ceph operational domains
- **DRY (Don't Repeat Yourself)**: Shared TokenOptimizer, reusable schema resolution
- **KISS (Keep It Simple, Stupid)**: Direct VictoriaLogs queries without translation layers

## Core Components

### 1. MCP Server Core
Central coordination component implementing Model Context Protocol.
📄 See: [docs/ARCHITECTURE.mcp-server-core.md](docs/ARCHITECTURE.mcp-server-core.md)

**Key Responsibilities:**
- MCP protocol handler registration
- Tool listing and invocation routing
- Session lifecycle management
- Mode-based tool handler selection

### 2. Tool Generation Engine
Dynamic tool creation from OpenAPI specifications.
📄 See: [docs/ARCHITECTURE.tool-generation-engine.md](docs/ARCHITECTURE.tool-generation-engine.md)

**Key Responsibilities:**
- OpenAPI spec parsing and analysis
- Three-mode tool generation (hybrid/base_only/categories_only)
- x-llm-hints integration
- Category-based endpoint grouping

### 3. Token Optimizer
Performance-critical component reducing LLM token consumption.
📄 See: [docs/ARCHITECTURE.token-optimizer.md](docs/ARCHITECTURE.token-optimizer.md)

**Key Responsibilities:**
- Response truncation with metadata
- grep-like filtering (regex, numeric, field existence)
- Field selection for verbose responses
- Default pagination limits

### 4. Log Search System
Advanced log analysis with VictoriaLogs integration.
📄 See: [docs/ARCHITECTURE.log-search-system.md](docs/ARCHITECTURE.log-search-system.md)

**Key Responsibilities:**
- Natural language intent parsing
- Direct VictoriaLogs JSON query execution
- WebSocket streaming with binary auth
- HTTP export fallback mechanism
- Log summarization and critical event extraction

### 5. API Client
HTTP/HTTPS communication layer for Croit cluster interaction.
📄 See: [ARCHITECTURE.api-client.md](docs/ARCHITECTURE.api-client.md)

**Key Responsibilities:**
- Bearer token authentication
- SSL verification management
- Request/response handling
- Error propagation

### 6. Schema Resolver
OpenAPI $ref resolution and JSON schema conversion.
📄 See: [ARCHITECTURE.schema-resolver.md](docs/ARCHITECTURE.schema-resolver.md)

**Key Responsibilities:**
- Recursive $ref resolution
- OpenAPI to JSON Schema conversion
- Pagination request schema special handling
- Property extraction from nested schemas

### 7. Configuration Manager
Multi-source configuration loading and validation.
📄 See: [ARCHITECTURE.configuration-manager.md](docs/ARCHITECTURE.configuration-manager.md)

**Key Responsibilities:**
- Environment variable parsing
- Config file loading
- Local vs bundled OpenAPI spec selection
- Feature flag management

## Functional Modules

### Permission-Based Filtering
Role-based access control for tools.
📄 See: [ARCHITECTURE.permission-based-filtering.md](docs/ARCHITECTURE.permission-based-filtering.md)

### Response Filtering
grep-like filtering system with advanced operators.
📄 See: [ARCHITECTURE.response-filtering.md](docs/ARCHITECTURE.response-filtering.md)

### Category Mapping
Domain-based endpoint organization.
📄 See: [ARCHITECTURE.category-mapping.md](docs/ARCHITECTURE.category-mapping.md)

### Intent Parsing
Natural language to structured query conversion.
📄 See: [ARCHITECTURE.intent-parsing.md](docs/ARCHITECTURE.intent-parsing.md)

### Service Name Translation
Ceph service name normalization.
📄 See: [ARCHITECTURE.service-name-translation.md](docs/ARCHITECTURE.service-name-translation.md)

## Workflows & Processes

### Server Initialization Flow
Multi-stage bootstrap sequence.
📄 See: [ARCHITECTURE.server-initialization-flow.md](docs/ARCHITECTURE.server-initialization-flow.md)

### Tool Generation Workflow
Mode-specific tool creation strategies.
📄 See: [ARCHITECTURE.tool-generation-workflow.md](docs/ARCHITECTURE.tool-generation-workflow.md)

### API Request Execution
Full lifecycle from invocation to optimized response.
📄 See: [ARCHITECTURE.api-request-execution.md](docs/ARCHITECTURE.api-request-execution.md)

### Log Search Execution
Dual-path log query execution with optimization.
📄 See: [ARCHITECTURE.log-search-execution.md](docs/ARCHITECTURE.log-search-execution.md)

### OpenAPI Spec Resolution
Multi-step reference resolution process.
📄 See: [ARCHITECTURE.openapi-spec-resolution.md](docs/ARCHITECTURE.openapi-spec-resolution.md)

## Integration Points

### VictoriaLogs WebSocket Protocol
Binary authentication and streaming log integration.
📄 See: [ARCHITECTURE.victorialogs-websocket-protocol.md](docs/ARCHITECTURE.victorialogs-websocket-protocol.md)

### Croit API REST Interface
Primary cluster communication channel.
📄 See: [ARCHITECTURE.croit-api-rest-interface.md](docs/ARCHITECTURE.croit-api-rest-interface.md)

### MCP Protocol Handlers
Standard Model Context Protocol implementation.
📄 See: [ARCHITECTURE.mcp-protocol-handlers.md](docs/ARCHITECTURE.mcp-protocol-handlers.md)

## Design Patterns

### Strategy Pattern: Tool Modes
Three operational strategies for tool generation.
📄 See: [ARCHITECTURE.strategy-pattern-tool-modes.md](docs/ARCHITECTURE.strategy-pattern-tool-modes.md)

### Builder Pattern: LogsQL
Structured query construction from intents.
📄 See: [ARCHITECTURE.builder-pattern-logsql.md](docs/ARCHITECTURE.builder-pattern-logsql.md)

### Adapter Pattern: OpenAPI
OpenAPI to MCP tool definition adaptation.
📄 See: [ARCHITECTURE.adapter-pattern-openapi.md](docs/ARCHITECTURE.adapter-pattern-openapi.md)

### Template Method: API Calls
Common execution structure with customization points.
📄 See: [ARCHITECTURE.template-method-api-calls.md](docs/ARCHITECTURE.template-method-api-calls.md)

## Utilities & Helpers

### Ceph Debug Templates
Pre-built query templates for common scenarios.
📄 See: [ARCHITECTURE.ceph-debug-templates.md](docs/ARCHITECTURE.ceph-debug-templates.md)

### Server ID Detector
Automatic server discovery from logs.
📄 See: [ARCHITECTURE.server-id-detector.md](docs/ARCHITECTURE.server-id-detector.md)

### Log Transport Analyzer
Kernel log availability analysis.
📄 See: [ARCHITECTURE.log-transport-analyzer.md](docs/ARCHITECTURE.log-transport-analyzer.md)

### Log Summary Engine
Priority breakdown and critical event extraction.
📄 See: [ARCHITECTURE.log-summary-engine.md](docs/ARCHITECTURE.log-summary-engine.md)

## Data Flow Diagrams

### API Call Flow
```
LLM Request → Tool Invocation → Schema Validation →
  → Token Optimization → HTTP Request → Croit API →
  → Response Filtering → Token Optimization → LLM Response
```

### Log Search Flow
```
LLM Query → Intent Parsing → LogsQL Building →
  → WebSocket Connection (or HTTP fallback) →
  → VictoriaLogs → Stream Processing →
  → Summarization → LLM Response
```

### Tool Generation Flow
```
Server Init → OpenAPI Fetch/Load → Schema Resolution →
  → Category Analysis → Permission Filtering →
  → Mode Selection (hybrid/base/categories) →
  → Tool Definition Creation → MCP Registration
```

## File Organization

### Module Structure
```
mcp-croit-ceph.py (2,212 lines)
├── CroitCephServer class
│   ├── Configuration (3 methods)
│   ├── OpenAPI handling (4 methods)
│   ├── Schema resolution (3 methods)
│   ├── API structure analysis (3 methods)
│   ├── Tool generation (6 methods)
│   ├── Tool handlers (6 methods)
│   └── Utility methods (4 methods)
└── main() entrypoint

token_optimizer.py (423 lines)
└── TokenOptimizer class
    ├── Truncation methods (2)
    ├── Filtering methods (6)
    ├── Summary generation (1)
    └── Utility methods (3)

croit_log_tools.py (2,661 lines)
├── LogSearchIntentParser (2 methods)
├── LogsQLBuilder (1 method)
├── CroitLogSearchClient (35+ methods)
├── CephServiceTranslator (5 methods)
├── CephDebugTemplates (2 methods)
├── ServerIDDetector (4 methods)
├── LogTransportAnalyzer (3 methods)
├── LogSummaryEngine (5 methods)
└── Handler functions (3)
```

## Dependencies

**External Libraries:**
- `mcp`: Model Context Protocol server implementation
- `aiohttp`: Async HTTP client for API calls
- `websockets`: WebSocket client for log streaming
- `requests`: Sync HTTP for OpenAPI spec fetching

**Internal Coupling:**
- mcp-croit-ceph.py imports: token_optimizer, croit_log_tools (optional)
- token_optimizer.py: standalone, no internal imports
- croit_log_tools.py: standalone, no internal imports

## Performance Characteristics

**Token Optimization Impact:**
- Default pagination: 90%+ token reduction on list operations
- Response truncation: Configurable limits (25-100 items)
- Field filtering: 50-70% reduction for verbose responses
- Hint suppression: 30-40% reduction on repeated list_endpoints calls

**Caching:**
- OpenAPI spec: In-memory, full application lifecycle
- Log search: 5-minute response cache per query hash

**Connection Pooling:**
- HTTP: aiohttp.ClientSession (persistent connections)
- WebSocket: Per-request connections (no pooling)

## Security Considerations

**Authentication:**
- Bearer token in Authorization header
- Binary WebSocket token authentication
- No credential storage (environment variables only)

**Permission Enforcement:**
- Role-based tool filtering (ADMIN vs VIEWER)
- Category-level access control
- No privilege escalation paths

**Input Validation:**
- OpenAPI schema validation for API calls
- Query parameter sanitization
- Regex pattern validation in filters

## Operational Modes

### Hybrid Mode (Default)
13 tools: 3 base discovery + 10 category-specific.
Optimal balance between flexibility and usability.

### Base Only Mode
3 tools: list_endpoints, call_endpoint, get_schema.
Minimal footprint for maximum control.

### Categories Only Mode
10-15 tools: One per major operational category.
Simplified interface for guided operations.

## Extensibility Points

1. **New Tool Modes**: Add to mode validation in `__init__`
2. **Additional Categories**: Extend category mapping in `_analyze_api_structure`
3. **Custom Optimizations**: Add methods to TokenOptimizer class
4. **Log Search Patterns**: Extend PATTERNS dict in LogSearchIntentParser
5. **Debug Templates**: Add to CephDebugTemplates.TEMPLATES

## Maintenance Guidelines

### When to Update Documentation

**File Changes:**
- New classes/functions: Update relevant ARCHITECTURE.<slug>.md
- Workflow changes: Update process documentation
- New dependencies: Update this document

**API Changes:**
- OpenAPI spec updates: No doc changes needed (dynamic)
- New x-llm-hints fields: Update tool-generation-engine.md
- New MCP protocol features: Update mcp-protocol-handlers.md

### Documentation Review Cycle

**Quarterly:** Review all process and workflow docs
**On Major Releases:** Full architecture audit
**On Refactoring:** Immediate updates to affected components

## Related Resources

- **User Guide**: README.md (integration and usage)
- **AI Assistant Instructions**: CLAUDE.md (LLM-specific guidance)
- **Build Configuration**: Dockerfile, build.sh
- **CI/CD Pipeline**: .gitlab-ci.yml, .github/workflows/

## Version History

**Current Architecture**: v0.4.x
**Last Major Revision**: 2024-10 (Modular documentation structure)
**Next Planned Revision**: TBD
