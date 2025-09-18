# Filter Usage Examples for MCP Croit Ceph

## Overview

The MCP server now includes grep-like filtering capabilities that allow the LLM to search and filter responses **locally** without making multiple API calls.

## Filter Syntax

All filter parameters start with `_filter_` prefix:

### 1. Simple Equality Filter
```json
{
  "_filter_status": "error"
}
```
Returns only items where `status == "error"`

### 2. Multiple Values (OR logic)
```json
{
  "_filter_status": ["error", "warning", "critical"]
}
```
Returns items where status is any of these values

### 3. Regex Pattern Search
Use `~` prefix for regex patterns:
```json
{
  "_filter_name": "~ceph.*pool"
}
```
Returns items where name matches the regex pattern (case-insensitive)

### 4. Numeric Comparisons
```json
{
  "_filter_size": ">1000000",
  "_filter_cpu_usage": "<=80",
  "_filter_count": ">=10"
}
```
Supported operators: `>`, `<`, `>=`, `<=`, `!=`, `=`

### 5. Full Text Search
Search across all string fields:
```json
{
  "_filter__text": "error"
}
```
Returns items containing "error" in any text field

### 6. Field Existence
Check if a field exists:
```json
{
  "_filter__has": "error_message"
}
```
Returns only items that have an `error_message` field

## Real-World Examples

### Find all errored OSDs
```
Tool: list_osds
Arguments:
{
  "_filter_status": "error"
}
```

### Find services on a specific server
```
Tool: list_services
Arguments:
{
  "_filter_hostname": "ceph-node-01"
}
```

### Find large pools (>1TB)
```
Tool: list_pools
Arguments:
{
  "_filter_used_bytes": ">1099511627776"
}
```

### Search for anything mentioning "timeout"
```
Tool: list_logs
Arguments:
{
  "_filter__text": "timeout",
  "limit": 50
}
```

### Find OSDs with high usage
```
Tool: list_osds
Arguments:
{
  "_filter_used_percent": ">80"
}
```

### Complex filter: Error services on specific nodes
```
Tool: list_services
Arguments:
{
  "_filter_status": ["error", "failed"],
  "_filter_hostname": "~ceph-node-0[1-3]"
}
```

## How It Works

1. **API Call**: Normal API call is made with standard parameters
2. **Response Received**: Full response from API
3. **Local Filtering**: Filters applied locally in Python
4. **Truncation**: After filtering, response is truncated if needed
5. **Return to LLM**: Filtered and optimized data

## Benefits

### Token Savings
- Instead of fetching 500 services to find errors, fetch all and filter locally
- Result: 5 error services instead of 500 total = 99% token savings

### Speed
- Single API call instead of multiple filtered calls
- Local filtering is instant

### Flexibility
- Combine multiple filters
- Use regex for complex patterns
- Search across all fields

## Implementation Details

The filtering happens in `token_optimizer.py`:
- `apply_filters()` - Main filter application
- `_item_matches_filters()` - Check single item
- `_text_search_in_item()` - Full text search
- `_numeric_comparison()` - Numeric comparisons

Integration in `mcp-croit-ceph.py`:
- Filters extracted from arguments with `_filter_` prefix
- Applied after API response, before truncation
- Works with all list/get operations