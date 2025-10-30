# MCP Server Core

## Overview

The MCP Server Core is the central coordination component implementing the Model Context Protocol. It registers handlers, routes tool invocations, and manages the server lifecycle.

**Module**: mcp-croit-ceph.py
**Class**: CroitCephServer
**Lines**: ~200 (initialization and handler registration)

## Purpose

Provides the bridge between MCP clients (LLMs) and the underlying Croit cluster operations by:
- Implementing MCP protocol specification
- Routing tool calls to appropriate handlers
- Managing configuration and initialization sequence
- Coordinating between API tools and log search subsystems

## Responsibilities

### 1. MCP Protocol Handler Registration
Registers standard MCP handlers during initialization:
- `list_tools()`: Returns available tools based on selected mode
- `call_tool()`: Routes invocations to mode-specific handlers

### 2. Tool Invocation Routing
Routes calls based on operational mode:
- **Hybrid mode**: Routes to `handle_hybrid_tool()`
- **Base only mode**: Routes to `handle_api_call_tool()`
- **Categories only mode**: Routes to `handle_category_tool()`

### 3. Session Lifecycle Management
- Creates aiohttp.ClientSession for persistent HTTP connections
- Manages server state throughout application lifecycle
- Handles graceful shutdown (session cleanup)

### 4. Mode-Based Initialization
Configures server based on selected mode:
- Analyzes API structure for category-based modes
- Prepares appropriate tool sets
- Sets up log search tools if enabled

## Dependencies

**Imports:**
- `mcp.server`: Server, NotificationOptions
- `mcp.server.models`: InitializationOptions
- `mcp.server.stdio`: Standard I/O communication
- `mcp.types`: MCP type definitions

**Internal Dependencies:**
- Tool Generation Engine (for tool creation)
- Configuration Manager (for settings)
- API Client (aiohttp session)
- Log Search System (optional, if enabled)

## Relations

**Coordinates:**
- Tool Generation Engine: Delegates tool creation
- API Client: Provides HTTP session
- Token Optimizer: Applies to responses
- Log Search System: Registers log tools

**Used By:**
- main() function (server instantiation)

## Key Methods

### `__init__()`
Multi-stage initialization:
1. Load configuration (host, token, mode settings)
2. Fetch or load OpenAPI spec
3. Resolve schema references (if enabled)
4. Analyze API structure (for hybrid/categories modes)
5. Generate tools based on mode
6. Register log search tools (if enabled)
7. Register MCP handlers

### Handler Registration Pattern
```
@self.server.list_tools()
async def list_tools_handler() -> list[types.Tool]:
    return await self.handle_list_tools()

@self.server.call_tool()
async def call_tool_handler(name: str, arguments: dict) -> list[types.TextContent]:
    # Route based on self.mode
    if self.mode == "hybrid":
        result = await self.handle_hybrid_tool(name, arguments)
    ...
```

### `handle_list_tools()`
Returns `self.mcp_tools` list, which contains all registered tools for the current mode.

### Mode-Specific Tool Handlers
- `handle_hybrid_tool()`: Routes to base tools, category tools, or log tools
- `handle_api_call_tool()`: Handles list/call/schema operations
- `handle_category_tool()`: Delegates to `_handle_category_tool()`

## Initialization Flow

```
Server Instantiation
    ↓
Configuration Loading (_load_config)
    ↓
OpenAPI Spec Acquisition
  ├── Local file (_load_local_swagger_spec)
  ├── Bundled spec (USE_INCLUDED_API_SPEC)
  └── Fetch from cluster (_fetch_swagger_spec)
    ↓
Schema Resolution (_resolve_swagger_references)
    ↓
Mode-Specific Preparation
  ├── hybrid → _prepare_hybrid_tools
  ├── base_only → _prepare_api_tools
  └── categories_only → _prepare_category_tools_only
    ↓
Optional: Add Log Tools (_add_log_search_tools)
    ↓
MCP Server Creation
    ↓
Handler Registration
    ↓
Ready for Requests
```

## Configuration Options

**Constructor Parameters:**
- `mode`: "hybrid" | "base_only" | "categories_only"
- `resolve_references`: bool (resolve OpenAPI $ref)
- `offer_whole_spec`: bool (include full spec in tools)
- `max_category_tools`: int (limit category tool count)
- `min_endpoints_per_category`: int (minimum for category creation)
- `openapi_file`: str | None (local OpenAPI path)
- `use_included_api_spec`: bool (use bundled spec)
- `enable_log_tools`: bool (enable log search)
- `enable_daos`: bool (include DAOS endpoints)
- `enable_specialty_features`: bool (include specialty endpoints)

**Environment Variables (via Configuration Manager):**
- `CROIT_HOST`: Cluster URL
- `CROIT_API_TOKEN`: Authentication token
- `USE_INCLUDED_API_SPEC`: Use bundled OpenAPI spec
- `CONFIG_PATH`: Path to config.json file

## Error Handling

**Initialization Errors:**
- Missing configuration → RuntimeError
- Invalid OpenAPI spec → Logged and raised
- Invalid mode → ValueError
- Permission check failure → Logged warning

**Runtime Errors:**
- Tool handler exceptions → RuntimeError with error message
- Network failures → Propagated to LLM as text response

## Performance Characteristics

**Initialization Time:**
- Local spec: <1s
- Fetch from cluster: 1-3s (network dependent)
- Schema resolution: +0.5-2s (if enabled)

**Memory Footprint:**
- OpenAPI spec: ~2-5 MB
- Tool definitions: ~50-500 KB depending on mode
- HTTP session: ~1 MB

**Connection Management:**
- Single aiohttp.ClientSession (persistent)
- Reuses connections across requests
- No connection pooling limits set

## Design Patterns

**Factory Pattern**: Creates different tool sets based on mode
**Strategy Pattern**: Mode selection determines behavior
**Facade Pattern**: Simplifies MCP protocol complexity

## Relevance

Read this document when:
- Understanding system initialization sequence
- Implementing new operational modes
- Debugging MCP protocol issues
- Extending handler registration logic
- Troubleshooting configuration problems

## Extension Points

1. **New Modes**: Add mode to validation and create preparation method
2. **Custom Handlers**: Register additional MCP handlers in `__init__`
3. **Initialization Hooks**: Add steps to initialization sequence
4. **Error Handlers**: Extend error handling in tool_handler

## Related Documentation

- [ARCHITECTURE.tool-generation-engine.md](ARCHITECTURE.tool-generation-engine.md) - Tool creation logic
- [ARCHITECTURE.configuration-manager.md](ARCHITECTURE.configuration-manager.md) - Configuration loading
- [ARCHITECTURE.server-initialization-flow.md](ARCHITECTURE.server-initialization-flow.md) - Detailed init sequence
- [ARCHITECTURE.mcp-protocol-handlers.md](ARCHITECTURE.mcp-protocol-handlers.md) - Protocol implementation
