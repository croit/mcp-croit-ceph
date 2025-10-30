# API Request Execution

## Overview

The API request execution workflow handles the complete lifecycle of an API call from tool invocation to optimized response delivery. It integrates token optimization, schema validation, and error handling.

**Module**: mcp-croit-ceph.py
**Methods**: `handle_hybrid_tool()`, `_call_endpoint_direct()`, `_make_api_call()`
**Duration**: 100-2000ms per request

## Purpose

Executes API requests with:
- Parameter validation and transformation
- Token optimization
- Response filtering
- Error handling and propagation
- Metadata enrichment

## Execution Flow

### Complete Request Lifecycle

```
LLM Tool Invocation
    ↓
Mode-Specific Handler
├── hybrid → handle_hybrid_tool()
├── base_only → handle_api_call_tool()
└── categories_only → handle_category_tool()
    ↓
Route to Appropriate Handler
├── Base tools → _list_endpoints_filtered()
│                _call_endpoint_direct()
│                _quick_find_endpoints()
├── Category tools → _handle_category_tool()
└── Log tools → _handle_log_search()
    ↓
Parameter Processing
├── Extract endpoint path
├── Extract HTTP method
├── Extract body/query parameters
├── Apply default pagination
└── Validate required fields
    ↓
Token Optimization (Pre-Request)
├── should_optimize()?
├── add_default_limit()
└── Note: filters for post-processing
    ↓
HTTP Request Execution (_make_api_call)
├── Build full URL
├── Add authorization header
├── Set SSL verification
├── Execute with aiohttp
└── Handle HTTP errors
    ↓
Response Processing
├── Parse JSON
├── Check for API errors
└── Extract data
    ↓
Token Optimization (Post-Response)
├── truncate_response()
├── apply_filters()
└── Add metadata
    ↓
Return to LLM
```

## Handler Methods

### `handle_hybrid_tool(name, arguments)`

Routes hybrid mode tool invocations.

**Logic**:
```python
if name in ["list_endpoints", "call_endpoint", "get_schema"]:
    # Base tools
    return await base_tool_handler(name, arguments)
elif name.startswith("manage_"):
    # Category tools
    category = name.replace("manage_", "")
    return await _handle_category_tool(category, arguments)
elif name in ["croit_log_search", "croit_log_check"]:
    # Log tools
    return await log_tool_handler(name, arguments)
else:
    raise ValueError(f"Unknown tool: {name}")
```

### `_call_endpoint_direct(arguments)`

Executes direct API endpoint calls.

**Input Arguments**:
```python
{
  "endpoint_path": "/api/services",
  "method": "GET",  # Optional, default: GET
  "query_params": {...},  # Optional
  "body_params": {...},  # Optional
  "path_params": {...}  # Optional for templates
}
```

**Processing Steps**:
1. Extract and validate endpoint path
2. Determine HTTP method (default: GET from spec)
3. Process path parameters (replace {id} templates)
4. Merge query parameters
5. Build request body
6. Apply token optimization
7. Execute request
8. Process response

### `_handle_category_tool(category, arguments)`

Handles category-specific tool invocations.

**Input Arguments**:
```python
{
  "action": "list|get|create|update|delete",
  "action_args": {...},  # Action-specific parameters
  "server_id": "...",  # Context-dependent
  "resource_id": "...",  # For get/update/delete
  "filters": {...}  # For list operations
}
```

**Action Routing**:
```python
if action == "list":
    endpoint = find_list_endpoint(category)
    method = "GET"
    params = action_args + default_pagination
elif action == "get":
    endpoint = find_get_endpoint(category)
    method = "GET"
    params = {"id": resource_id}
elif action == "create":
    endpoint = find_create_endpoint(category)
    method = "POST"
    body = action_args
elif action == "update":
    endpoint = find_update_endpoint(category)
    method = "PUT" or "PATCH"
    body = action_args
elif action == "delete":
    endpoint = find_delete_endpoint(category)
    method = "DELETE"
    params = {"id": resource_id}
```

## HTTP Request Execution

### `_make_api_call(endpoint_path, method, params, body)`

Low-level HTTP execution.

**Request Construction**:
```python
url = f"{self.host}{endpoint_path}"
headers = {
    "Authorization": f"Bearer {self.api_token}",
    "Content-Type": "application/json"
}

# Apply SSL verification
verify_ssl = self.ssl

# Execute with aiohttp
async with self.session.request(
    method=method,
    url=url,
    params=params,
    json=body,
    headers=headers,
    ssl=verify_ssl
) as response:
    data = await response.json()
    return data
```

**Error Handling**:
- 4xx errors → API error message to LLM
- 5xx errors → Server error message to LLM
- Network errors → Connection error to LLM
- Timeout → Timeout error to LLM

## Token Optimization Integration

### Pre-Request Optimization

**Method**: `TokenOptimizer.add_default_limit()`

Applied to GET requests on list endpoints:
```python
if TokenOptimizer.should_optimize(url, method):
    params = TokenOptimizer.add_default_limit(url, params)
```

**Default Limits**:
- Services/servers: limit=25
- OSDs: limit=30
- Stats: limit=50
- Logs: limit=100
- General: limit=10

### Post-Response Optimization

**Method**: `TokenOptimizer.truncate_response()`

Applied to all list responses:
```python
if isinstance(response_data, list) and len(response_data) > max_items:
    response_data = TokenOptimizer.truncate_response(response_data, url)
```

**Result**:
```python
{
  "data": [truncated items],
  "_truncation_metadata": {
    "truncated": true,
    "original_count": 500,
    "returned_count": 25,
    "truncation_message": "..."
  }
}
```

### Filter Application

**Method**: `TokenOptimizer.apply_filters()`

Applied when `_filter_*` parameters present:
```python
filters = extract_filters(params)  # _filter_status, _filter_name, etc.
if filters:
    response_data = TokenOptimizer.apply_filters(response_data, filters)
```

## Parameter Processing

### Query Parameter Handling

**Standard Parameters**:
- `limit`, `offset`: Pagination
- `sort`, `order`: Sorting
- `filter`: Generic filtering

**Filter Parameters** (custom):
- `_filter_status=error`: Exact match
- `_filter_name=~ceph.*`: Regex
- `_filter_size=>1000`: Numeric comparison
- `_filter__text=timeout`: Full-text search
- `_filter__has=error_message`: Field existence

**Processing**:
```python
def extract_filters(params):
    filters = {}
    for key, value in params.items():
        if key.startswith("_filter_"):
            field = key.replace("_filter_", "")
            filters[field] = value
            del params[key]  # Remove from query params
    return filters
```

### Body Parameter Handling

**For POST/PUT/PATCH**:
```python
body = arguments.get("body_params", {})
# Validate required fields from OpenAPI schema
# Apply defaults
# Convert types as needed
```

### Path Parameter Handling

**Template Replacement**:
```python
path_params = arguments.get("path_params", {})
for key, value in path_params.items():
    endpoint_path = endpoint_path.replace(f"{{{key}}}", str(value))

# Example: "/servers/{id}/disks" + {"id": "1"} → "/servers/1/disks"
```

## Response Processing

### Success Response

**Standard Format**:
```python
{
  "data": [...],  # or single object
  "metadata": {
    "count": 100,
    "limit": 25,
    "offset": 0
  }
}
```

**Processed Format**:
```python
{
  "data": [...],  # Potentially truncated
  "_optimization_applied": true,
  "_original_count": 100,
  "_returned_count": 25,
  "_truncation_metadata": {...}  # If truncated
}
```

### Error Response

**API Error**:
```python
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "Server with ID 999 not found",
    "details": {...}
  }
}
```

**Passed to LLM as**:
```python
{
  "error": "API Error: Server with ID 999 not found",
  "error_code": "RESOURCE_NOT_FOUND",
  "suggestion": "Check server ID and try again"
}
```

## Pagination Handling

### Automatic Pagination

**Detection**:
```python
def _endpoint_requires_pagination(endpoint_path):
    # Check if endpoint typically returns lists
    return any(indicator in endpoint_path for indicator in [
        "/list", "/all", "get_all"
    ])
```

**Default Pagination**:
```python
def _get_default_pagination(category):
    if category in ["logs", "audit"]:
        return {"limit": 100, "offset": 0}
    elif category in ["services", "servers"]:
        return {"limit": 25, "offset": 0}
    else:
        return {"limit": 10, "offset": 0}
```

### Manual Pagination

**User-Specified**:
```python
{
  "query_params": {
    "limit": 50,
    "offset": 100
  }
}
```

**Overrides**: User-specified values override automatic defaults

## Error Handling Strategy

### Retry Logic

**Transient Errors** (retried):
- Connection timeout (max 3 retries)
- 503 Service Unavailable (exponential backoff)
- Network connection reset

**Permanent Errors** (not retried):
- 400 Bad Request
- 401 Unauthorized
- 403 Forbidden
- 404 Not Found

### Error Enrichment

**Context Added**:
```python
{
  "error": "Original error message",
  "endpoint": "/api/services",
  "method": "GET",
  "suggestion": "Check authentication token",
  "related_hints": [...]  # From x-llm-hints
}
```

## Performance Characteristics

**Typical Timing**:
- Parameter processing: 1-5ms
- HTTP request: 50-500ms
- Response parsing: 5-20ms
- Token optimization: 10-100ms
- **Total**: 100-700ms

**With Truncation**:
- Large response (1000 items): +50-200ms
- Filter application: +10-50ms per filter

## Caching Considerations

**No Built-In Caching** for API calls:
- Every request hits the cluster
- Ensures fresh data
- Allows real-time updates

**Log Search Caching**:
- 5-minute cache for log queries
- Separate from API request flow

## Design Patterns

**Template Method**: Common execution structure with customization points
**Chain of Responsibility**: Error handling propagation
**Decorator Pattern**: Token optimization wrapping
**Strategy Pattern**: Mode-specific routing

## Extension Points

1. **Custom Handlers**: Add to mode routing logic
2. **Optimization Strategies**: Extend TokenOptimizer integration
3. **Error Handling**: Add custom error processors
4. **Response Transformers**: Post-processing pipelines
5. **Caching Layer**: Add response caching

## Relevance

Read this document when:
- Understanding request execution flow
- Debugging API call issues
- Implementing custom handlers
- Optimizing request performance
- Adding new token optimization strategies
- Troubleshooting parameter handling

## Related Documentation

- [ARCHITECTURE.token-optimizer.md](ARCHITECTURE.token-optimizer.md) - Optimization logic
- [ARCHITECTURE.response-filtering.md](ARCHITECTURE.response-filtering.md) - Filter details
- [ARCHITECTURE.mcp-protocol-handlers.md](ARCHITECTURE.mcp-protocol-handlers.md) - Handler registration
- [ARCHITECTURE.croit-api-rest-interface.md](ARCHITECTURE.croit-api-rest-interface.md) - API interface
