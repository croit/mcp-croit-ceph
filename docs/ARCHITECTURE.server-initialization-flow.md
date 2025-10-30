# Server Initialization Flow

## Overview

The server initialization flow is a multi-stage bootstrap sequence that configures, loads specifications, generates tools, and prepares the MCP server for operation.

**Module**: mcp-croit-ceph.py
**Entry Point**: `CroitCephServer.__init__()`, `main()`
**Duration**: 1-5 seconds (depending on spec source)

## Purpose

Establishes a fully configured MCP server by:
- Loading configuration from multiple sources
- Acquiring OpenAPI specifications
- Resolving schema references
- Analyzing API structure
- Generating appropriate tools
- Registering MCP protocol handlers

## Initialization Stages

### Stage 1: Configuration Loading

**Method**: `_load_config()`

**Sources (in priority order)**:
1. Environment variables (`CROIT_HOST`, `CROIT_API_TOKEN`)
2. Config file (`/config/config.json` or `CONFIG_PATH`)
3. Defaults (none for required values)

**Actions**:
- Read host URL
- Read API token
- Strip trailing slashes
- Detect SSL (https prefix)
- Validate presence of required values

**Failure**: RuntimeError if host or token missing

### Stage 2: OpenAPI Spec Acquisition

**Three possible paths**:

#### Path A: Use Included Spec
**Condition**: `use_included_api_spec=True` OR `USE_INCLUDED_API_SPEC=1`
**Method**: Loads bundled `openapi.json` from package directory
**Advantages**: Offline operation, consistent tooling, fast startup
**Duration**: <100ms

#### Path B: Load Local File
**Condition**: `openapi_file` parameter provided
**Method**: `_load_local_swagger_spec()`
**Actions**:
- Read file from specified path
- Parse JSON
- Validate structure
**Advantages**: Custom/test specs, version control
**Duration**: 100-500ms

#### Path C: Fetch from Cluster
**Condition**: No local spec specified
**Method**: `_fetch_swagger_spec()`
**Actions**:
- HTTP GET to `{host}/api/swagger.json`
- Bearer token authentication
- SSL verification based on protocol
- JSON parsing
**Advantages**: Always current, no manual updates
**Duration**: 1-3s (network dependent)

**Failure Handling**:
- Invalid JSON → Logged and raised
- Network error → Logged and raised
- 401/403 → Authentication error

### Stage 3: Schema Resolution (Optional)

**Condition**: `resolve_references=True` (default)
**Method**: `_resolve_swagger_references()`

**Actions**:
1. Identify all `$ref` references in spec
2. Recursively resolve each to actual schema
3. Replace reference with resolved content
4. Special handling for `PaginationRequest` (string representation)

**Impact**:
- Increases spec size 2-3x
- Eliminates $ref lookup during runtime
- Duration: 500-2000ms

**Rationale**: Some LLMs can't handle $ref, need inline schemas

### Stage 4: API Structure Analysis (Mode-Dependent)

**Condition**: Mode is `hybrid` or `categories_only`
**Method**: `_analyze_api_structure()`

**Actions**:
1. Extract all paths and operations from OpenAPI
2. Identify tags/categories per endpoint
3. Count endpoints per category
4. Build `category_endpoints` mapping
5. Apply feature flags (DAOS, specialty features)

**Output**:
```python
self.category_endpoints = {
  "ceph-pools": [endpoint1, endpoint2, ...],
  "services": [endpoint1, endpoint2, ...],
  ...
}
```

**Duration**: 200-500ms

### Stage 5: Permission Checking (Optional)

**Condition**: `--no-permission-check` NOT specified
**Method**: `_get_user_roles()`

**Actions**:
1. Call `/auth/token-info` endpoint
2. Extract roles from response
3. Store in `self.user_roles`
4. Filter categories by permission

**Admin Detection**:
- If "ADMIN" in roles: all categories allowed
- Otherwise: filter out admin-only categories

**Failure**: Logs warning, continues with all categories

### Stage 6: Mode-Specific Tool Generation

**Three possible paths**:

#### Mode: Hybrid (Default)
**Method**: `_prepare_hybrid_tools()`

**Actions**:
1. Create 3 base tools (list/call/schema)
2. Sort categories by endpoint count
3. Select top N categories (default: 10)
4. Generate category tool for each
5. Add to `self.mcp_tools`

**Output**: ~13 tools

#### Mode: Base Only
**Method**: `_prepare_api_tools()`

**Actions**:
1. Create list_api_endpoints tool
2. Create call_api_endpoint tool
3. Create get_reference_schema tool
4. Add to `self.mcp_tools`

**Output**: 3 tools

#### Mode: Categories Only
**Method**: `_prepare_category_tools_only()`

**Actions**:
1. Generate category tool for each category
2. Apply permission filtering
3. Add to `self.mcp_tools`

**Output**: 10-15 tools

**Duration**: 300-1000ms depending on mode

### Stage 7: Log Tools Registration (Optional)

**Condition**: `enable_log_tools=True` AND `croit_log_tools` module available
**Method**: `_add_log_search_tools()`

**Actions**:
1. Create `croit_log_search` tool definition
2. Create `croit_log_check` tool definition
3. Create `croit_log_monitor` tool definition (optional)
4. Add to `self.mcp_tools`

**Output**: +3 tools

### Stage 8: MCP Server Creation

**Actions**:
1. Create `Server("mcp-croit-ceph")` instance
2. Store in `self.server`

**Duration**: <10ms

### Stage 9: Handler Registration

**Handlers Registered**:
1. `list_tools()` → `handle_list_tools()`
2. `call_tool()` → Mode-specific handler

**Handler Selection Logic**:
```python
if self.mode == "hybrid":
    handler = self.handle_hybrid_tool
elif self.mode == "categories_only":
    handler = self.handle_category_tool
else:  # base_only
    handler = self.handle_api_call_tool
```

**Duration**: <10ms

### Stage 10: Server Start

**Method**: `main()`

**Actions**:
1. Parse command line arguments
2. Instantiate CroitCephServer (runs all above stages)
3. Start MCP server with stdio transport
4. Enter event loop

**Output**: Server ready for MCP requests

## Initialization Flow Diagram

```
main()
  ↓
Parse CLI Arguments
  ↓
CroitCephServer.__init__()
  ├─→ _load_config()
  │   ├── CROIT_HOST
  │   ├── CROIT_API_TOKEN
  │   └── Feature flags
  │
  ├─→ OpenAPI Spec Acquisition
  │   ├── Bundled? → Load from package
  │   ├── File? → _load_local_swagger_spec()
  │   └── Remote? → _fetch_swagger_spec()
  │
  ├─→ resolve_references?
  │   └── Yes → _resolve_swagger_references()
  │
  ├─→ Mode requires analysis?
  │   └── Yes → _analyze_api_structure()
  │       └── _filter_categories_by_permission()
  │
  ├─→ Tool Generation (mode-specific)
  │   ├── hybrid → _prepare_hybrid_tools()
  │   ├── base_only → _prepare_api_tools()
  │   └── categories_only → _prepare_category_tools_only()
  │
  ├─→ enable_log_tools?
  │   └── Yes → _add_log_search_tools()
  │
  ├─→ Create MCP Server
  │
  └─→ Register Handlers
      ├── list_tools
      └── call_tool
  ↓
mcp.server.stdio.run()
  ↓
Event Loop (Ready for Requests)
```

## Configuration Validation

**Required Settings**:
- `CROIT_HOST`: Must be valid URL
- `CROIT_API_TOKEN`: Must be non-empty string

**Optional Settings**:
- `mode`: Defaults to "hybrid"
- `max_category_tools`: Defaults to 10
- `enable_log_tools`: Defaults to True
- `enable_daos`: Defaults to False
- `enable_specialty_features`: Defaults to True

**Validation Points**:
1. Mode validation: Must be in ["hybrid", "base_only", "categories_only"]
2. OpenAPI spec: Must be valid JSON
3. Token: Will be validated on first API call

## Performance Characteristics

**Timing Breakdown (typical hybrid mode)**:
- Configuration: 10ms
- Fetch OpenAPI: 1-3s (or 100ms if local)
- Resolve references: 500-2000ms
- Analyze structure: 200-500ms
- Generate tools: 300-1000ms
- Register handlers: 10ms
- **Total**: 2-7s (or 1-4s with local spec)

**Memory Footprint**:
- OpenAPI spec: 2-5 MB
- Resolved spec: 5-15 MB (if resolution enabled)
- Tool definitions: 50-500 KB
- HTTP session: ~1 MB
- **Total**: 8-21 MB

## Error Handling

**Critical Errors (halt initialization)**:
- Missing CROIT_HOST or CROIT_API_TOKEN
- Invalid OpenAPI spec file
- Network failure fetching spec
- Invalid mode specified

**Non-Critical Errors (logged warnings)**:
- Permission check failure → Continue with all categories
- Log tools unavailable → Continue without log tools
- Token optimizer unavailable → Continue without optimization

## Environment Variables

**Core**:
- `CROIT_HOST`: Cluster URL (required)
- `CROIT_API_TOKEN`: API token (required)

**Optional**:
- `USE_INCLUDED_API_SPEC`: Use bundled spec (1/true/yes/on)
- `CONFIG_PATH`: Path to config.json
- `LOG_LEVEL`: Logging verbosity (DEBUG/INFO/WARN/ERROR)

**Passed to Tools**:
All environment variables available during initialization are passed to handler functions.

## Design Patterns

**Template Method**: Initialization sequence with customization points
**Factory Pattern**: Mode-specific tool creation
**Builder Pattern**: Incremental configuration and setup
**Lazy Initialization**: HTTP session created but not connected until first use

## Extension Points

1. **New Configuration Sources**: Add to `_load_config()` method
2. **Custom Validation**: Add checks after config loading
3. **Initialization Hooks**: Add steps between existing stages
4. **Mode-Specific Setup**: Add new preparation methods
5. **Post-Initialization Tasks**: Add after handler registration

## Troubleshooting

**Slow Startup**:
- Use local or bundled OpenAPI spec
- Disable reference resolution
- Reduce max_category_tools

**Initialization Failures**:
- Check CROIT_HOST accessibility
- Verify API token validity
- Review OpenAPI spec validity
- Check file permissions for local specs

**Missing Tools**:
- Verify mode selection
- Check permission filtering
- Confirm log tools module installed

## Relevance

Read this document when:
- Understanding system startup
- Debugging initialization errors
- Optimizing startup performance
- Adding initialization steps
- Understanding configuration precedence
- Troubleshooting missing tools

## Related Documentation

- [ARCHITECTURE.mcp-server-core.md](ARCHITECTURE.mcp-server-core.md) - Server core component
- [ARCHITECTURE.configuration-manager.md](ARCHITECTURE.configuration-manager.md) - Configuration loading
- [ARCHITECTURE.tool-generation-engine.md](ARCHITECTURE.tool-generation-engine.md) - Tool creation
- [ARCHITECTURE.openapi-spec-resolution.md](ARCHITECTURE.openapi-spec-resolution.md) - Schema resolution
