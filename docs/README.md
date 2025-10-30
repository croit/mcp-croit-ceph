# Architecture Documentation

This directory contains modular architecture documentation for the MCP Croit Ceph server.

## Overview

Each document focuses on a specific component, workflow, integration point, design pattern, or utility. Documents follow consistent structure:
- Overview / Purpose
- Responsibilities
- Dependencies and Relations
- Relevance / When to Read
- Design Patterns Used
- References to related files

## Quick Navigation

### Core Components
- **[ARCHITECTURE.mcp-server-core.md](ARCHITECTURE.mcp-server-core.md)** - Central MCP protocol implementation
- **[ARCHITECTURE.tool-generation-engine.md](ARCHITECTURE.tool-generation-engine.md)** - Dynamic tool creation from OpenAPI
- **[ARCHITECTURE.token-optimizer.md](ARCHITECTURE.token-optimizer.md)** - Performance optimization (90%+ token savings)
- **[ARCHITECTURE.log-search-system.md](ARCHITECTURE.log-search-system.md)** - VictoriaLogs integration and log analysis

### Workflows (To be created)
- ARCHITECTURE.server-initialization-flow.md
- ARCHITECTURE.tool-generation-workflow.md
- ARCHITECTURE.api-request-execution.md
- ARCHITECTURE.log-search-execution.md
- ARCHITECTURE.openapi-spec-resolution.md

### Integration Points (To be created)
- ARCHITECTURE.victorialogs-websocket-protocol.md
- ARCHITECTURE.croit-api-rest-interface.md
- ARCHITECTURE.mcp-protocol-handlers.md

### Functional Modules (To be created)
- ARCHITECTURE.permission-based-filtering.md
- ARCHITECTURE.response-filtering.md
- ARCHITECTURE.category-mapping.md
- ARCHITECTURE.intent-parsing.md
- ARCHITECTURE.service-name-translation.md

### Design Patterns (To be created)
- ARCHITECTURE.strategy-pattern-tool-modes.md
- ARCHITECTURE.builder-pattern-logsql.md
- ARCHITECTURE.adapter-pattern-openapi.md
- ARCHITECTURE.template-method-api-calls.md

### Utilities (To be created)
- ARCHITECTURE.ceph-debug-templates.md
- ARCHITECTURE.server-id-detector.md
- ARCHITECTURE.log-transport-analyzer.md
- ARCHITECTURE.log-summary-engine.md

## For LLMs

When you need to understand specific aspects of the system:

1. **Start with**: [../ARCHITECTURE.md](../ARCHITECTURE.md) for high-level overview
2. **Dive into**: Specific component docs for detailed implementation
3. **Trace workflows**: Read process documents for end-to-end understanding
4. **Understand patterns**: Review design pattern docs for architectural decisions

## Documentation Standards

Each architecture document includes:
- **Module/File Reference**: Where to find the code
- **Line Count**: Complexity indicator
- **Purpose**: What problem it solves
- **Responsibilities**: What it does
- **Dependencies**: What it needs
- **Relations**: How it connects to other components
- **Relevance**: When to read this document
- **Extension Points**: How to extend functionality

## Creating New Documentation

When adding new components or significant functionality:
1. Create `ARCHITECTURE.<lowercase-slug>.md` in this directory
2. Follow the established structure and format
3. Add reference in main `../ARCHITECTURE.md`
4. Update this README's navigation section
5. Cross-reference related documents

## Version

**Documentation Structure Created**: 2024-10-30
**Current Version**: v0.4.x compatible
**Status**: Core components documented, workflows and patterns pending
