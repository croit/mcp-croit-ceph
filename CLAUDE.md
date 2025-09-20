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

### 3. Enhanced VictoriaLogs Integration

#### `croit_log_search` - Advanced Log Analysis
**Revolutionary direct VictoriaLogs JSON interface** with intelligent enhancements:

🚀 **NEW FEATURES:**
- **Smart Summaries**: Priority breakdown, service analysis, critical event extraction
- **Intelligent Truncation**: Critical events prioritized over chronological order
- **Log Level Shortcuts**: `search_errors()`, `search_warnings()`, `search_info()`, `search_critical()`
- **Server Auto-Discovery**: Automatic detection of available server IDs
- **Transport Analysis**: Debug kernel log availability with multiple strategies
- **Template Queries**: 10 pre-built debugging scenarios
- **Response Optimization**: Configurable size limits with critical event preservation

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

### 4. NEW: Advanced Debug Features

#### Log Level Shortcuts 🎯
Quick access to specific priority levels:

```python
# Critical/Emergency logs (priority ≤2)
await client.search_critical("OSD failures", hours_back=48, limit=50)

# Error logs (priority ≤3)
await client.search_errors("authentication", hours_back=24, limit=100)

# Warning logs (priority ≤4)
await client.search_warnings("slow requests", hours_back=24, limit=200)

# Info logs (priority ≤6)
await client.search_info("startup sequence", hours_back=6, limit=500)
```

#### Server Auto-Discovery 🖥️
Automatic detection of available server IDs:

```python
# Discover servers from recent logs
server_info = await client.discover_servers()
# Returns: server IDs, hostnames, activity levels, service distribution

# Get human-readable summary
summary = await client.get_server_summary()
# "🖥️ Detected 3 active server(s):
#  🟢 Server 1 (new-croit-host-C0DE01): 1,247 logs (45.2%), 8 services
#  🟢 Server 2 (ceph-node-02): 982 logs (35.6%), 6 services"
```

#### Kernel Log Debugging 🔍
Multiple strategies to find kernel logs:

```python
# Analyze all available transport types
transports = await client.analyze_log_transports(hours_back=24)
# Shows: kernel, syslog, journal distributions with sample messages

# Debug kernel log availability
kernel_debug = await client.find_kernel_logs_debug(hours_back=24)
# Tests: direct kernel transport, syslog+kernel identifier, message content, hardware keywords
```

#### Template Queries 🛠️
Pre-built debugging scenarios:

```python
templates = CephDebugTemplates.get_templates()
# Available templates:
# - osd_health_check: OSD failures, flapping, performance issues
# - cluster_status_errors: Critical cluster-wide errors
# - slow_requests: Slow operations and blocked requests
# - pg_issues: Placement Group problems
# - network_errors: Connectivity timeouts, heartbeat issues
# - mon_election: Monitor election problems
# - storage_errors: Disk errors, SMART failures
# - kernel_ceph_errors: Kernel-level Ceph messages
# - rbd_mapping_issues: RBD client problems
# - recent_startup: Service startup sequences

# Use template
template = CephDebugTemplates.get_template_by_scenario('osd_health_check')
# Returns complete query with optimal time range and limits
```

#### Response Size Optimization 📊
Intelligent size control:

```python
# Optimized search (automatic)
result = await client.search_optimized("OSD errors", limit=1000, optimize_response=True)
# Applies: 50 log max, 150 char messages, critical events first

# Manual optimization
optimized = client.optimize_response_size(
    data=search_result,
    max_log_entries=30,
    max_message_length=100
)
```

#### Smart Summaries 📈
Comprehensive log analysis:

```python
# Included in all search results:
{
  "summary": {
    "summary": "📊 Log Analysis Summary - 1,247 total entries\n🚨 5 critical events\n❌ 23 errors\n⚠️ 89 warnings",
    "priority_breakdown": {"ERROR": 23, "WARNING": 89, "INFO": 1135},
    "service_breakdown": {"ceph-osd@12": 456, "ceph-mon": 234},
    "critical_events": [
      {
        "priority": "ERROR",
        "timestamp": "2023-...",
        "service": "ceph-osd@12",
        "message_preview": "OSD failed to start: cannot access block device...",
        "score": -15  # Lower = more critical
      }
    ],
    "trends": {
      "peak_hours": [["2023-12-20 14:00", 234]],
      "busiest_service": "ceph-osd@12"
    },
    "recommendations": [
      "🚨 Immediate attention needed: 5 critical events",
      "💾 Multiple OSD issues detected - check storage health"
    ]
  }
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

## Development & Testing

⚠️ **CRITICAL**: This project requires a virtual environment due to system-managed Python.

### Initial Setup
```bash
# Create and activate virtual environment (REQUIRED)
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install aiohttp websockets  # For log search functionality
```

### Testing Commands
```bash
# Always activate virtual environment first
source venv/bin/activate

# Test timestamp calculation fix
python test_timestamp_fix.py

# Test MCP functionality
CROIT_API_TOKEN="your-token" python test_actual_mcp.py

# Run basic MCP server test
python mcp-croit-ceph.py --openapi-file openapi.json --no-permission-check
```

## ⚠️ CRITICAL: Run Black Formatter Before EVERY Commit!

**GitLab CI WILL FAIL if Python code is not formatted with black!**

### Pre-Commit Checklist
```bash
# ALWAYS run before committing:
source venv/bin/activate
black --check .  # Check for issues
black .          # Fix formatting
```

**Why this is critical:**
- The GitLab CI pipeline runs `black --check` in the lint stage
- Unformatted code causes pipeline failures
- This blocks merging and deployment

### Quick Fix for Lint Failures
```bash
# If you forgot to run black and CI failed:
source venv/bin/activate
black croit_log_tools.py mcp-croit-ceph.py token_optimizer.py
git add -u
git commit -m "fix: Apply black formatting"
git push
```

## ⚠️ IMPORTANT: openapi.json is Auto-Generated

**DO NOT EDIT openapi.json DIRECTLY** - The file is automatically generated from the Croit API backend!

### OpenAPI Spec Updates
The `openapi.json` file is fetched from the Croit cluster and contains the API specification with x-llm-hints. To update x-llm-hints, changes must be made in the Croit API backend source code, not in this MCP project.

Current status (as of v0.4.0):
- **580** total API endpoints
- **575** endpoints with x-llm-hints (99.1% coverage)
- **5** endpoints missing x-llm-hints

### Missing/Inadequate x-llm-hints for Critical OSD Operations

**Problem:** LLMs cannot find correct OSD removal workflow without specific hints.

**Critical Issues Found:**
1. `DELETE /servers/{id}/disks/{diskId}` - Has generic "disk record removal" hints instead of OSD-specific guidance
2. `DELETE /disks/wipe` - Missing "400 if active OSD" failure mode and workflow guidance

These hints need to be updated in the source (likely the Croit API backend that generates openapi.json) to provide proper OSD operation guidance for LLMs.

### Common Development Patterns
```bash
# Start development session
source venv/bin/activate
export LOG_LEVEL=DEBUG
export CROIT_API_TOKEN="your-token"

# Run tests
python test_timestamp_fix.py
python test_actual_mcp.py
```