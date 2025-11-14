# Token Optimization System

## Overview

The MCP Croit Ceph server includes an intelligent token optimization system that drastically reduces LLM token consumption while preserving the ability to access detailed data when needed.

## How It Works

### Three-Tier Strategy

1. **Small Responses (≤5 items)**: Returned as-is, no optimization needed
2. **Medium Responses (6-50 items)**: Truncated to 25 items with metadata
3. **Large Responses (>50 items)**: Smart summary with drill-down capability

### Smart Summary

For large responses, the system generates an intelligent summary containing:

- **Total count**: Number of items in the full response
- **Status breakdown**: Distribution by status (e.g., 90 ok, 10 error)
- **Critical items**: Items with errors or warnings
- **Sample items**: First 3 items as examples
- **Available fields**: List of all fields in the response
- **Response ID**: Unique identifier for drill-down

**Token Savings**: Typically 80-95% reduction!

## Usage Example

### Step 1: Make API Call (Gets Summary)

```javascript
// LLM calls:
call_api_endpoint({
  endpoint: "/pools",
  method: "get"
})

// Response (optimized):
{
  "_summary": "Found 100 items",
  "_response_id": "f6a7dece",
  "total_count": 100,
  "by_status": {
    "ok": 90,
    "error": 10
  },
  "errors_found": 10,
  "error_samples": [
    {"id": 10, "name": "pool-10", "status": "error", ...},
    {"id": 20, "name": "pool-20", "status": "error", ...}
  ],
  "sample_items": [...],
  "available_fields": ["id", "name", "status", "size", "used", ...],
  "_hint": "Use search_last_result(response_id='f6a7dece') to filter/search"
}
```

### Step 2: Drill Down for Details

```javascript
// LLM wants to see only errors:
search_last_result({
  response_id: "f6a7dece",
  filters: {
    status: "error"
  },
  limit: 20
})

// Response (full details for errors only):
{
  "response_id": "f6a7dece",
  "matched_count": 10,
  "results": [
    {"id": 10, "name": "pool-10", "status": "error", ...},
    {"id": 20, "name": "pool-20", "status": "error", ...},
    // ... all 10 error pools with complete data
  ]
}
```

## Filter Examples

### Exact Match
```javascript
{status: "error"}
{type: "replicated"}
```

### Substring Search
```javascript
{name__contains: "osd"}
{path__contains: "/dev/sd"}
```

### Numeric Comparisons
```javascript
{size__gt: 1000000}        // Greater than
{used__lt: 500000}         // Less than
{objects__gte: 1000}       // Greater or equal
```

### Full-Text Search
```javascript
{_filter__text: "ceph osd"}
```

### Combined Filters
```javascript
{
  status: "error",
  type: "replicated",
  size__gt: 1000000
}
```

## Token Savings Analysis

Based on testing with 100 pool objects:

| Metric | Original | Optimized | Savings |
|--------|----------|-----------|---------|
| Characters | 12,128 | 1,856 | 10,272 (84.7%) |
| Estimated Tokens | 3,032 | 464 | 2,568 (84.7%) |

**Real-world impact**:
- **500 OSDs**: ~15,000 tokens → ~1,000 tokens (93% savings)
- **200 RBDs**: ~8,000 tokens → ~800 tokens (90% savings)
- **1000 servers**: ~50,000 tokens → ~2,000 tokens (96% savings)

## Error Handling

The system preserves full error context:

1. **Error detection**: Automatically identifies items with errors
2. **Error prioritization**: Error items included in summary samples
3. **Full details available**: Use `search_last_result()` for complete error data

## Session Storage

- Full responses stored in memory with unique response IDs
- Allows drill-down without re-fetching from cluster API
- Automatic cleanup (keeps last 10 responses)
- Thread-safe for concurrent requests

## Caching

In addition to session storage, the system includes:

- **5-15 minute cache** for GET requests
- **Automatic cache invalidation** on TTL expiry
- **LRU eviction** when cache is full (100 entries max)
- **Cache bypass**: Use `no_optimize=true` parameter

## Configuration

Token optimization is **enabled by default** and requires no configuration.

To disable for specific requests:
```javascript
call_api_endpoint({
  endpoint: "/pools",
  method: "get",
  query_params: {no_optimize: true}
})
```

## Best Practices

1. **Use summaries first**: Review the summary before drilling down
2. **Filter aggressively**: Use specific filters to reduce data
3. **Leverage response IDs**: Reference stored responses for follow-up queries
4. **Check error samples**: Review error samples in summary before fetching all
5. **Use field lists**: Summary shows available fields for targeted queries

## Architecture

```
API Request
    ↓
Cache Check
    ↓
API Response (full data)
    ↓
Token Optimizer
    ├─ Small (≤5): Pass through
    ├─ Medium (6-50): Truncate to 25
    └─ Large (>50): Smart Summary
           ├─ Store full data (response_id)
           ├─ Generate summary
           └─ Return summary
    ↓
LLM receives optimized response
    ↓
(Optional) search_last_result(response_id, filters)
    ↓
Return filtered full data
```

## Implementation Details

- **Module**: `token_optimizer.py`
- **Main classes**: `TokenOptimizer`, `ResponseCache`
- **Key functions**: 
  - `optimize_api_response()`: Main optimization entry point
  - `create_smart_summary()`: Summary generation
  - `search_stored_response()`: Drill-down search

## Log Search Token Protection (NEW in v0.5.0)

### Problem

Log searches for verbose services (e.g., Ceph MON) could return 1000+ log entries, causing 200k+ token responses that exceed LLM context limits.

### Solution: Multi-Level Protection

**Level 1: Reduced Default Limit**
- `DEFAULT_LOG_LIMIT` reduced from 1000 → 50 entries
- Prevents massive responses by default

**Level 2: Priority-Based Truncation**
- If response exceeds `MAX_LOG_ENTRIES_IN_RESPONSE` (50):
  - Sort logs by severity (ERROR > WARN > INFO)
  - Return top 50 most critical entries
  - Add truncation warning

**Level 3: Message Truncation**
- Long messages truncated to `MAX_LOG_MESSAGE_LENGTH` (200 chars)
- Adds `_message_truncated: true` flag

**Level 4: Intelligent Summary**
- Always generated, regardless of size
- Provides:
  - Priority breakdown (ERROR: 5, WARN: 23, INFO: 972)
  - Service distribution
  - Top 5 critical events
  - Statistics and recommendations

**Level 5: Size Warning**
- Estimates total response size
- Warns if exceeds `MAX_LOG_RESPONSE_CHARS` (50k chars ≈ 12.5k tokens)

### Example Response

```json
{
  "code": 200,
  "result": {
    "summary": {
      "text": "📊 Log Analysis Summary - Showing 50 of 1,247 entries (truncated)\n🚨 5 ERRORS found\n⚠️ 23 WARNINGS found\n\n📦 Top Services:\n  • osd: 456 entries\n  • mon: 234 entries",
      "priority_breakdown": {"ERROR": 5, "WARN": 23, "INFO": 22},
      "critical_events": [
        {
          "priority": "ERROR",
          "service": "osd",
          "message_preview": "OSD failed to start: cannot access block device...",
          "score": -10
        }
      ]
    },
    "logs": [...50 most critical logs...],
    "total_count": 50,
    "original_count": 1247,
    "was_truncated": true,
    "truncation_info": "Truncated from 1247 to 50 logs (prioritized by severity)"
  }
}
```

### Token Savings

| Scenario | Before | After | Savings |
|----------|--------|-------|---------|
| MON logs (1000 entries) | 200k+ tokens | ~15k tokens | 92.5% |
| OSD logs (500 entries) | 100k+ tokens | ~15k tokens | 85% |
| General search (50 entries) | ~10k tokens | ~10k tokens | 0% (not truncated) |

### Configuration Constants

```python
# src/config/constants.py
DEFAULT_LOG_LIMIT = 50                    # Reduced from 1000
MAX_LOG_ENTRIES_IN_RESPONSE = 50          # Hard limit
MAX_LOG_MESSAGE_LENGTH = 200              # Char limit per message
MAX_LOG_RESPONSE_CHARS = 50000            # Warning threshold
```

## Future Enhancements

- Configurable thresholds (currently hardcoded: 5, 50)
- Persistent storage for response IDs across sessions
- Automatic expiry of old responses (currently keeps all in memory)
- Compression for very large stored responses
- Statistics tracking for optimization effectiveness
- User-configurable log limits per query
