# Token Optimizer

## Overview

The Token Optimizer is a standalone performance-critical module that reduces LLM token consumption by up to 90% through intelligent response filtering, truncation, and summarization.

**Module**: token_optimizer.py
**Class**: TokenOptimizer
**Lines**: 423
**Type**: Utility module (no internal dependencies)

## Purpose

Minimizes token usage in LLM interactions without losing critical information by:
- Automatically truncating large responses with metadata
- Applying grep-like filters to narrow results
- Selecting essential fields from verbose responses
- Adding smart pagination defaults
- Generating summaries for large datasets

## Responsibilities

### 1. Response Truncation
Limits response size while preserving usefulness:
- Configurable item limits (default: 25-100 based on type)
- Metadata about truncation (original count, truncation message)
- Guidance on how to get more data

### 2. grep-like Filtering
Client-side filtering without additional API calls:
- Exact matching
- Regex patterns
- Numeric comparisons (>, <, >=, <=, =, !=)
- Full-text search across all fields
- Field existence checks
- Multiple value matching (OR logic)

### 3. Field Selection
Reduces verbosity by keeping only essential fields:
- Predefined essential field sets per resource type
- Configurable field lists
- Recursive filtering for nested objects

### 4. Default Pagination
Adds smart pagination limits:
- Type-aware defaults (logs: 100, services: 25, stats: 50)
- Only adds if no existing pagination parameters
- Logged for transparency

### 5. Summary Generation
Creates compact summaries for large datasets:
- Count-only summaries
- Statistical summaries (status/type distributions)
- Error-only filtering
- Sample data inclusion

## Dependencies

**External:**
- logging: For optimization activity logging
- re: For regex pattern matching
- json: For data manipulation

**None**: Completely standalone, no internal dependencies

## Relations

**Used By:**
- MCP Server Core (`_make_api_call` method)
- Tool Generation Engine (hint integration)

**Integration Points:**
- Applied before returning responses to LLM
- Hints added to tool descriptions
- No direct coupling to other components

## Key Methods

### `should_optimize(url, method) → bool`
Determines if request should be optimized.

**Logic:**
- Only GET requests
- URL contains: `/list`, `/all`, `get_all`, `/export`
- Returns False for POST/PUT/DELETE

**Purpose**: Avoid unnecessary optimization on single-item or modification requests

### `add_default_limit(url, params) → Dict`
Adds pagination limit if not present.

**Parameters Checked:**
- limit, max, size, offset, page

**Limits by URL Pattern:**
- `/logs`, `/audit`: 100
- `/stats`: 50
- `/services`, `/servers`: 25
- `/osds`: 30
- Default: 10

**Return**: Modified params dict with `limit` key

### `truncate_response(data, url, max_items=50) → Any`
Truncates large list responses.

**Behavior:**
- Non-list data: pass through unchanged
- Lists ≤ max_items: pass through unchanged
- Large lists: truncate with metadata

**Type-Specific Limits:**
- Logs/audit: up to 100 items
- Stats: up to 75 items
- Services/servers/osds: up to 25 items

**Return Format:**
```
{
  "data": [truncated items],
  "_truncation_metadata": {
    "truncated": true,
    "original_count": 500,
    "returned_count": 25,
    "truncation_message": "Response truncated... Use pagination or filters..."
  }
}
```

### `apply_filters(data, filters) → Any`
Applies grep-like filters to data.

**Filter Syntax:**
- `{"status": "error"}`: Exact match
- `{"status": ["error", "warning"]}`: Multiple values (OR)
- `{"name": "~ceph.*"}`: Regex (~ prefix)
- `{"size": ">1000"}`: Numeric comparison
- `{"_text": "timeout"}`: Full-text search
- `{"_has": "error_message"}`: Field existence
- `{"_has": ["field1", "field2"]}`: Multiple fields (AND)

**Return**: Filtered data (list or single item)

### `filter_fields(data, resource_type) → Any`
Selects only essential fields.

**Essential Fields by Type:**
- servers: id, hostname, ip, status, role
- services: id, name, type, status, hostname
- osds: id, osd, status, host, used_percent, up
- pools: name, pool_id, size, used_bytes, percent_used
- rbds: name, pool, size, used_size
- s3: bucket, owner, size, num_objects
- tasks: id, name, status, progress, error
- logs: timestamp, level, service, message

**Return**: Data with only specified fields

### `generate_summary(data, summary_type) → Dict`
Generates compact summaries.

**Summary Types:**
- `count`: Just total count
- `stats`: Count + distributions + sample
- `errors_only`: Only error items (max 10)

**Stats Summary Includes:**
- total_count
- sample (first 3 items)
- status_distribution (if status field exists)
- type_distribution (if type field exists)

**Return**: Summary dictionary

## Filter Implementation Details

### Numeric Comparison Logic
**Method**: `_numeric_comparison(value, comparison)`

**Supported Operators:**
- `>=50`: Greater than or equal
- `<=50`: Less than or equal
- `>50`: Greater than
- `<50`: Less than
- `=50`: Equal to
- `!=50`: Not equal to

**Error Handling**: Returns False for non-numeric values

### Text Search Implementation
**Method**: `_text_search_in_item(item, search_text)`

**Search Behavior:**
- Case-insensitive
- Searches all string fields recursively
- Handles nested dicts and lists
- Returns True if found anywhere

### Item Matching Logic
**Method**: `_item_matches_filters(item, filters)`

**Algorithm:**
- All filters must match (AND logic)
- Special filters: `_text`, `_has`
- Regular field filters processed sequentially
- First failed filter → immediate False return

## Performance Characteristics

**Truncation Performance:**
- List slicing: O(1) operation
- Metadata creation: O(1)
- No deep copying

**Filtering Performance:**
- Linear scan: O(n) where n = item count
- Regex compilation: Cached by Python's `re` module
- Text search: O(n*m) where m = field count

**Memory Usage:**
- Truncation: Creates new small list (efficient)
- Filtering: Creates new list, old data eligible for GC
- Field selection: Creates new dicts (minimal overhead)

## Token Savings Analysis

**Typical Scenarios:**

**Scenario 1: List All Services**
- Without optimization: 500 services × 20 fields × 5 tokens/field = 50,000 tokens
- With truncation (25 items): 25 × 20 × 5 = 2,500 tokens
- Savings: 95%

**Scenario 2: Filter Services by Status**
- Without filter: Fetch all 500, LLM filters → 50,000 tokens
- With _filter_status="error": 5 services × 20 × 5 = 500 tokens
- Savings: 99%

**Scenario 3: Essential Fields Only**
- Full response: 100 servers × 50 fields × 5 = 25,000 tokens
- Essential fields (5): 100 × 5 × 5 = 2,500 tokens
- Savings: 90%

## Integration Pattern

```python
# In MCP Server Core (_make_api_call)
response_data = await api_call()

# Apply optimization if enabled
if TokenOptimizer.should_optimize(url, method):
    # Add default limits (before request)
    params = TokenOptimizer.add_default_limit(url, params)

    # After response
    response_data = TokenOptimizer.truncate_response(response_data, url)

    # Apply user filters
    if filters:
        response_data = TokenOptimizer.apply_filters(response_data, filters)

return response_data
```

## Design Patterns

**Utility Pattern**: Static methods, no instance state
**Strategy Pattern**: Different optimization strategies per data type
**Filter Chain Pattern**: Multiple filters applied sequentially

## Extension Points

1. **New Resource Types**: Add to `ESSENTIAL_FIELDS` dict
2. **Custom Limits**: Extend `DEFAULT_LIMITS` dict
3. **New Filter Operators**: Add to `apply_filters` method
4. **Summary Types**: Extend `generate_summary` method
5. **Optimization Hints**: Add to `add_optimization_hints` method

## Usage Examples

### Basic Truncation
```python
large_list = [... 500 items ...]
result = TokenOptimizer.truncate_response(large_list, "/api/services")
# Returns: {"data": [... 25 items ...], "_truncation_metadata": {...}}
```

### Filtering
```python
services = [{"name": "ceph-osd@12", "status": "running"}, ...]
errors = TokenOptimizer.apply_filters(services, {"status": "error"})
```

### Combined Optimization
```python
# Start with 500 services
data = fetch_services()  # 500 items

# Truncate to 25
data = TokenOptimizer.truncate_response(data, "/services")  # 25 items

# Filter to errors only
data = TokenOptimizer.apply_filters(data, {"status": "error"})  # 3 items

# Keep essential fields only
data = TokenOptimizer.filter_fields(data, "services")  # Compact format
```

## Relevance

Read this document when:
- Optimizing token consumption
- Implementing response filtering
- Adding new resource types
- Debugging filter behavior
- Understanding performance impact
- Extending optimization strategies

## Related Documentation

- [ARCHITECTURE.response-filtering.md](ARCHITECTURE.response-filtering.md) - Detailed filter behavior
- [ARCHITECTURE.api-request-execution.md](ARCHITECTURE.api-request-execution.md) - Integration points
- [ARCHITECTURE.tool-generation-engine.md](ARCHITECTURE.tool-generation-engine.md) - Hint integration
