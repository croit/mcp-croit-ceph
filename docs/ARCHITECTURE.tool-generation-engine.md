# Tool Generation Engine

## Overview

The Tool Generation Engine dynamically creates MCP tools from OpenAPI specifications with integrated x-llm-hints. It operates in three distinct modes, each generating a different tool topology.

**Module**: mcp-croit-ceph.py
**Methods**: `_prepare_hybrid_tools()`, `_prepare_category_tools_only()`, `_prepare_api_tools()`, `_generate_category_tool()`
**Lines**: ~800 (tool generation logic)

## Purpose

Transforms static OpenAPI specifications into dynamic, LLM-optimized tool definitions that:
- Expose Croit API functionality through MCP protocol
- Integrate x-llm-hints for intelligent LLM guidance
- Reduce token consumption through strategic tool organization
- Support flexible operational modes for different use cases

## Responsibilities

### 1. OpenAPI Spec Parsing
- Extracts paths, operations, parameters from OpenAPI
- Identifies tags/categories for grouping
- Processes x-llm-hints annotations

### 2. Three-Mode Tool Generation
- **Hybrid Mode**: 3 base tools + top 10 category tools (~13 total)
- **Base Only Mode**: 3 universal tools (list/call/schema)
- **Categories Only Mode**: 10-15 category-specific tools

### 3. x-llm-hints Integration
Incorporates vendor extensions into tool descriptions:
- Purpose statements
- Usage examples
- Request/response parameters
- Failure modes and error handling
- Rate limits and retry strategies
- Related endpoints and workflows

### 4. Category-Based Endpoint Grouping
Organizes endpoints by operational domains:
- ceph-pools, rbds, osds
- servers, services, disks
- cluster, maintenance, logs
- s3, cephfs, authentication

## Dependencies

**Data Structures:**
- `self.api_spec`: Parsed OpenAPI specification
- `self.category_endpoints`: Map of category → endpoint list
- `self.mcp_tools`: Generated tool definitions

**External:**
- mcp.types.Tool: Tool definition structure
- TokenOptimizer: Adds optimization hints

## Relations

**Called By:**
- MCP Server Core initialization

**Uses:**
- Schema Resolver (for parameter extraction)
- Permission-Based Filtering (for role checks)
- Category Mapping (for endpoint organization)

## Operational Modes

### Hybrid Mode (Default)

**Tool Count**: ~13 tools
**Strategy**: Combine universal access with common operations

**Base Tools**:
1. `list_endpoints`: Searchable endpoint directory with hints
2. `call_endpoint`: Direct API invocation with optimization
3. `get_schema`: Schema reference resolution

**Category Tools** (top 10 by endpoint count):
- Pools, Services, Servers, OSDs, etc.
- Each supports: list, get, create, update, delete actions
- Integrated x-llm-hints from all endpoints in category

**Advantages:**
- Optimal balance: flexibility + ease of use
- Reduced tool discovery overhead (13 vs 580)
- Common operations accessible without search
- Full API coverage through base tools

### Base Only Mode

**Tool Count**: 3 tools
**Strategy**: Minimal footprint, maximum control

**Tools:**
1. `list_api_endpoints`: Search/filter all endpoints
2. `call_api_endpoint`: Invoke any endpoint
3. `get_reference_schema`: Resolve schemas

**Advantages:**
- Smallest token footprint
- No predetermined categories
- Full endpoint discovery capability
- Suitable for exploratory use

### Categories Only Mode

**Tool Count**: 10-15 tools
**Strategy**: Guided interface for common operations

**Tool Generation**:
- One tool per major category
- Pre-filters endpoints by permission
- Includes all x-llm-hints for category
- Supports standard CRUD actions

**Advantages:**
- Simplified interface
- Domain-oriented organization
- No need to search endpoints
- Suitable for role-specific interfaces

## Tool Generation Process

### Hybrid Mode Generation

```
_prepare_hybrid_tools()
    ↓
1. Create Base Tools
   ├── list_endpoints (with intent filtering)
   ├── call_endpoint (with token optimization)
   └── get_schema (reference resolution)
    ↓
2. Analyze Categories
   - Count endpoints per category
   - Sort by endpoint count (descending)
   - Apply permission filtering
    ↓
3. Generate Category Tools (top N)
   For each category:
     ├── Extract all endpoints
     ├── Collect x-llm-hints
     ├── Build tool description
     ├── Define input schema
     └── Add to mcp_tools
    ↓
4. Feature Flags
   - Filter DAOS endpoints (if disabled)
   - Filter specialty features (if disabled)
    ↓
Result: mcp_tools populated with ~13 tools
```

### Category Tool Generation

**Method**: `_generate_category_tool(category: str)`

**Steps:**
1. **Endpoint Collection**: Filter by tag/category
2. **Permission Check**: Skip if user lacks access
3. **Hint Aggregation**: Collect x-llm-hints from all endpoints
4. **Description Building**:
   - Category overview
   - Supported actions (list/get/create/update/delete)
   - Aggregated purposes from hints
   - Usage patterns
   - Token optimization tips
   - Parameter documentation
5. **Schema Definition**:
   - action: enum of available operations
   - action_args: object for action-specific parameters
   - server_id, resource_id, etc. (context-dependent)
6. **Tool Registration**: Add to mcp_tools list

## x-llm-hints Integration

### Hint Fields Processed

**Core Fields:**
- `purpose`: What the endpoint does
- `usage`: Common use cases and workflows
- `request_parameters`: Parameter documentation
- `response_shape`: Expected response structure
- `failure_modes`: Common errors and causes
- `error_handling`: How to handle specific errors
- `retry_strategy`: Retry behavior guidance
- `rate_limit`: API throttling information
- `poll_interval`: Recommended refresh rates
- `cache_hint`: Caching strategy
- `related_endpoints`: Cross-references

### Hint Processing Strategy

**Deduplication**: Same hints across endpoints → single mention
**Prioritization**: Most common purposes listed first
**Token Optimization**:
- First call: Full hints included
- Subsequent calls: `has_hints: true` flag only
- Controlled by `hints_shown` state flag

## Permission-Based Filtering

**Method**: `_filter_categories_by_permission()`

**Admin-Only Categories**:
- maintenance, servers, ipmi
- config, hooks, change-requests
- config-templates

**Logic**:
1. Fetch user roles via `/auth/token-info`
2. If ADMIN role present: all categories allowed
3. Otherwise: filter out admin-only categories

**Integration Point**: Called during category tool generation

## Feature Flags

### DAOS Endpoint Filtering
**Flag**: `enable_daos` (default: False)
**Impact**: Removes ~54 DAOS-specific endpoints (~9.3% reduction)
**Categories Affected**: `daos`, `daos-pools`, `daos-containers`

### Specialty Features Filtering
**Flag**: `enable_specialty_features` (default: True)
**Impact**: Removes ~30 endpoints (~5.2% reduction)
**Categories Affected**: `rbd-mirror`, `iscsi`, `nfs-ganesha`

**Combined Impact**: ~84 endpoints removed (14.5% reduction)

## Token Optimization Integration

### Default Limits
TokenOptimizer adds default limits to tool descriptions:
- List operations: `limit=10`
- Services/servers: `limit=25`
- Stats: `limit=50`
- Logs: `limit=100`

### Filter Documentation
Tools include filter examples:
- `_filter_status="error"`: Exact match
- `_filter_name="~ceph.*"`: Regex
- `_filter_size=">1000"`: Numeric comparison
- `_filter__text="timeout"`: Full-text search
- `_filter__has="error_message"`: Field existence

## Category Priority Ranking

**Top Categories (by endpoint count)**:
1. ceph-pools (9 endpoints)
2. rbds (17 endpoints)
3. osds, servers (~15 each)
4. services, cluster (~12 each)
5. maintenance, s3 (~10 each)
6. disks, logs (~8 each)
7. cephfs, auth (~5 each)

**Selection Strategy**: Top `max_category_tools` categories by count

## Performance Characteristics

**Generation Time:**
- Hybrid mode: ~500ms (10 categories analyzed)
- Base only: <100ms (3 simple tools)
- Categories only: ~1s (all categories processed)

**Tool Payload Size:**
- Base tool: ~500 bytes each
- Category tool: ~2-5 KB (with hints)
- Total hybrid mode: ~25-50 KB

## Design Patterns

**Strategy Pattern**: Mode selection determines generation strategy
**Builder Pattern**: Incremental tool definition construction
**Factory Pattern**: Creates different tool types based on input
**Template Method**: Common tool generation structure with variations

## Extension Points

1. **New Modes**: Add mode to `__init__` validation and create `_prepare_*_tools()` method
2. **Custom Categories**: Extend category mapping in `_analyze_api_structure()`
3. **Hint Formats**: Modify hint processing in `_generate_category_tool()`
4. **Tool Schemas**: Customize JSON schemas for specific categories
5. **Priority Algorithm**: Change category selection logic

## Relevance

Read this document when:
- Understanding tool generation logic
- Implementing new operational modes
- Debugging tool definition issues
- Optimizing token usage strategies
- Adding custom endpoint categories
- Troubleshooting x-llm-hints integration

## Related Documentation

- [ARCHITECTURE.mcp-server-core.md](ARCHITECTURE.mcp-server-core.md) - Server initialization
- [ARCHITECTURE.category-mapping.md](ARCHITECTURE.category-mapping.md) - Category organization
- [ARCHITECTURE.permission-based-filtering.md](ARCHITECTURE.permission-based-filtering.md) - Access control
- [ARCHITECTURE.strategy-pattern-tool-modes.md](ARCHITECTURE.strategy-pattern-tool-modes.md) - Mode patterns
- [ARCHITECTURE.adapter-pattern-openapi.md](ARCHITECTURE.adapter-pattern-openapi.md) - OpenAPI adaptation
