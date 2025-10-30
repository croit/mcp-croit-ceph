# Architecture Documentation

Detailed component documentation for the MCP Croit Ceph server.

## Quick Navigation

### Core Components (4)
- **[ARCHITECTURE.mcp-server-core.md](ARCHITECTURE.mcp-server-core.md)** - Central MCP protocol implementation
- **[ARCHITECTURE.tool-generation-engine.md](ARCHITECTURE.tool-generation-engine.md)** - Dynamic tool creation from OpenAPI
- **[ARCHITECTURE.token-optimizer.md](ARCHITECTURE.token-optimizer.md)** - Performance optimization (90%+ token savings)
- **[ARCHITECTURE.log-search-system.md](ARCHITECTURE.log-search-system.md)** - VictoriaLogs integration and log analysis

### Key Workflows (3)
- **[ARCHITECTURE.server-initialization-flow.md](ARCHITECTURE.server-initialization-flow.md)** - Multi-stage bootstrap sequence
- **[ARCHITECTURE.api-request-execution.md](ARCHITECTURE.api-request-execution.md)** - Complete API request lifecycle
- **[ARCHITECTURE.log-search-execution.md](ARCHITECTURE.log-search-execution.md)** - Dual-path log query execution

## For LLMs

**Start with**: [../ARCHITECTURE.md](../ARCHITECTURE.md) for complete system overview

**Dive into**: Specific component docs for implementation details

## Documentation Standards

Each document includes:
- Module/file reference
- Purpose and responsibilities
- Dependencies and relations
- Relevance (when to read)
- Extension points

## Version

**Documentation Created**: 2024-10-30
**Current Version**: v0.4.x compatible
**Total Files**: 7 architecture documents + this index
