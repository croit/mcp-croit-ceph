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

### 3. Log Search Tools

#### `croit_log_search`
Natural language log searching with pattern detection.

**Examples:**
```
"Find OSD failures in the last hour"
"Show slow requests on node5"
"What errors occurred during pool creation"
"Debug authentication failures"
```

**Returns:**
- Generated LogsQL query
- Matching logs (limited to 100)
- Detected patterns (error clusters, bursts)
- Insights and recommendations

#### `croit_log_monitor`
Real-time log monitoring for specific conditions.

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

## Tips for Effective Use

1. **Combine tools**: Use logs to understand issues, then API calls to fix them
2. **Think in patterns**: Look for recurring issues, not just individual errors
3. **Use natural language**: The log search understands context and intent
4. **Monitor changes**: Use log monitoring during maintenance operations
5. **Document findings**: Note patterns for future reference

## Mode Selection

The server operates in different modes:

- **hybrid** (default): Both base tools and category-specific tools
- **base_only**: Only fundamental tools (list, call, schema)
- **categories_only**: Only category-organized tools
- **endpoints_as_tools**: Each API endpoint as individual tool (verbose)

Choose based on your preference for organization vs. flexibility.