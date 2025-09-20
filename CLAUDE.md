# Croit MCP Server - Claude Integration Guide

## Quick Start

The Croit MCP server provides intelligent access to Croit Ceph cluster management with advanced log search capabilities.

## Available Tools

### 1. API Tools (Base/Hybrid Mode)

- **list_api_endpoints**: Lists available API endpoints with filtering
- **call_api_endpoint**: Calls any API endpoint directly
- **get_reference_schema**: Gets schema definitions for API responses

### 2. Category Tools (Hybrid/Category Mode)

Organized by functional areas like:
- `croit_servers_*`: Server management operations
- `croit_pools_*`: Pool operations
- `croit_services_*`: Service management
- `croit_cluster_*`: Cluster operations

### 3. VictoriaLogs Integration

#### `croit_log_search`
**Revolutionary direct VictoriaLogs JSON interface** - No translation layer!

**Direct VictoriaLogs Syntax:**
```json
{
  "where": {
    "_and": [
      {"_SYSTEMD_UNIT": {"_contains": "ceph-osd@12"}},
      {"PRIORITY": {"_lte": 4}}
    ]
  },
  "hours_back": 1
}
```

**Comprehensive Operators:**
- **String:** `_eq`, `_contains`, `_starts_with`, `_regex`
- **Numeric:** `_eq`, `_neq`, `_gt`, `_gte`, `_lt`, `_lte`
- **Lists:** `_in`, `_nin`
- **Logic:** `_and`, `_or`, `_not`

**All Ceph Fields Supported:**
- `_SYSTEMD_UNIT`, `PRIORITY`, `CROIT_SERVER_ID`
- `_TRANSPORT`, `_HOSTNAME`, `_MACHINE_ID`
- `SYSLOG_IDENTIFIER`, `THREAD`, `MESSAGE`

#### `croit_log_check`
Instant log condition checking (non-blocking).

**Usage:**
```json
{
  "conditions": ["OSD failures", "Slow requests over 5s"],
  "duration": 60,
  "threshold": 5
}
```

## Natural Language to LogsQL

The system automatically converts natural language to optimized queries:

| Your Question | Generated LogsQL |
|--------------|------------------|
| "Find OSD failures" | `service:ceph-osd AND (level:ERROR OR _msg:"OSD failed")` |
| "Slow requests last hour" | `_msg:"slow request" AND _time:[now-1h, now]` |
| "Errors on node5" | `host:node5 AND level:ERROR` |
| "Pool full warnings" | `_msg:"pool" AND _msg:"full" AND level:WARN` |

## Pattern Detection

Automatically detects:
- **Error Clusters**: Groups similar errors
- **Time Bursts**: High-volume log periods
- **Service Dependencies**: Cross-service correlations
- **Anomalies**: Statistical outliers

## Filter Usage

### Basic Filters
```
_filter_status=active
_filter_name=~ceph.*
_filter_size=>1000
```

### Advanced Filters
```
_filter__text=search_term    # Full-text search
_filter__has=field_name      # Has field
_filter_field=!value         # Not equals
```

### Operators
- `=` : Exact match
- `~` : Regex match
- `>`, `<`, `>=`, `<=` : Numeric comparisons
- `!` : Negation
- `,` : Multiple values (OR)

## Usage Patterns

### Investigating Issues

**User**: "Why is the cluster slow?"
```
1. Use: croit_log_search("slow requests performance issues last hour")
2. Analyze patterns in results
3. Check specific services if patterns found
4. Use: croit_cluster_status() for current state
```

### Monitoring Operations

**User**: "Monitor pool creation"
```
1. Start: croit_log_monitor(["pool create", "pool errors"], duration=300)
2. Create pool with: croit_pools_create(...)
3. Check monitor results for issues
```

### Root Cause Analysis

**User**: "OSD.5 keeps failing"
```
1. Search: croit_log_search("OSD.5 failures errors last day")
2. Check patterns for repeated errors
3. Look for correlated events (network, disk)
4. Get OSD details: call_api_endpoint("/osds/5")
```

## Best Practices

### For Log Searching
1. **Start broad, then narrow**: First search generally, then add specific filters
2. **Use time ranges**: Always specify reasonable time windows
3. **Check patterns**: Look for repeated errors before investigating individual logs
4. **Correlate events**: When you find an error, search for related events

### For API Calls
1. **Use pagination**: Set reasonable limits (10-100 items)
2. **Apply filters early**: Use _filter parameters to reduce data
3. **Cache results**: Reuse data when possible
4. **Batch operations**: Group related calls

### Performance Tips
- Narrow time ranges for faster log searches
- Use service filters when possible
- Set appropriate limits on results
- Leverage the 5-minute cache for repeated queries

## Common Workflows

### Health Check
```
1. croit_cluster_status()
2. If issues found: croit_log_search("errors warnings last hour")
3. For specific service: croit_services_list(_filter_status=error)
```

### Troubleshooting
```
1. Identify symptom: croit_log_search("description of problem")
2. Find patterns in results
3. Drill down: search for specific error patterns
4. Check affected components: use appropriate API calls
5. Monitor fix: croit_log_monitor(["expected resolution"])
```

### Capacity Planning
```
1. Get pool stats: croit_pools_list()
2. Check growth: croit_log_search("pool capacity warnings")
3. Review trends: analyze patterns over time
4. Plan expansion: check server capacity
```

## Error Handling

### WebSocket Connection Failed
- Automatically falls back to HTTP
- Check network connectivity if persistent
- Verify VictoriaLogs service status

### No Logs Found
- Broaden search terms
- Extend time range
- Check service names are correct
- Verify cluster has logging enabled

### API Errors
- Check authentication token
- Verify endpoint exists (use list_api_endpoints)
- Check required parameters in schema
- Review error message for specifics

## VictoriaLogs Real-World Examples

### Monitor Logs on Server 1
```json
{
  "where": {
    "_and": [
      {"_SYSTEMD_UNIT": {"_contains": "ceph-mon"}},
      {"PRIORITY": {"_lte": 6}},
      {"CROIT_SERVER_ID": {"_eq": "1"}}
    ]
  }
}
```

### Kernel Errors with Text Search
```json
{
  "where": {
    "_and": [
      {"_TRANSPORT": {"_eq": "kernel"}},
      {"PRIORITY": {"_lte": 4}}
    ]
  },
  "_search": "error"
}
```

### Multiple OSDs, Specific Priority Range
```json
{
  "where": {
    "_and": [
      {"_SYSTEMD_UNIT": {"_regex": "ceph-osd@(12|13|14)"}},
      {"PRIORITY": {"_in": [0, 1, 2, 3, 4]}}
    ]
  }
}
```

## Tips for Effective Use

1. **Direct VictoriaLogs**: Use JSON syntax for precise control
2. **Current time context**: Timestamps are provided automatically
3. **Control messages**: Listen for "empty", "too_wide" feedback
4. **Combine tools**: Use logs to understand issues, then API calls to fix them
5. **Smart filtering**: Start broad, then narrow with specific operators

## Mode Selection

The server operates in different modes:

- **hybrid** (default): Both base tools and category-specific tools
- **base_only**: Only fundamental tools (list, call, schema)
- **categories_only**: Only category-organized tools
- **endpoints_as_tools**: Each API endpoint as individual tool (verbose)

Choose based on your preference for organization vs. flexibility.

## Performance Optimization Flags

### Feature Flags (Startup)
```bash
# Disable DAOS endpoints (saves ~54 endpoints, 9.3% reduction)
--enable-daos=false

# Disable specialty features (saves ~30 endpoints, 5.2% reduction)
--disable-specialty-features

# Maximum reduction (saves ~84 endpoints, 14.5% reduction)
--disable-specialty-features
```

### Intent-based Filtering (Runtime)
```bash
# When searching endpoints, specify your intent:
list_endpoints(search="pool", intent="read")    # Only GET operations
list_endpoints(search="rbd", intent="write")    # Only POST/PUT/PATCH
list_endpoints(search="osd", intent="read")     # OSD status/metadata (works!)
list_endpoints(search="osd", intent="manage")   # Only DELETE operations

# Quick access to specific resource types:
quick_find(resource_type="osds")                # All OSD-related endpoints
quick_find(resource_type="ceph-pools")          # Only Ceph pool endpoints
```

### Token Savings Examples
```
Standard pool search: 81 endpoints
+ deprecated filtered: 80 endpoints (1% reduction)
+ intent="read": 33 endpoints (59% reduction)
+ intent="write": 36 endpoints (56% reduction)
+ intent="manage": 12 endpoints (85% reduction)
+ priority + intent: ~9 endpoints (89% reduction)

Total API: 580 endpoints
+ deprecated filtered: 573 endpoints (1.2% reduction)
+ DAOS disabled: 519 endpoints (10.5% reduction)
+ specialty disabled: 489 endpoints (15.7% reduction)
+ all flags: 482 endpoints (16.9% reduction)
```