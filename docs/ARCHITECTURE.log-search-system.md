# Log Search System

## Overview

The Log Search System is a comprehensive subsystem for advanced log analysis with direct VictoriaLogs integration. It features natural language intent parsing, WebSocket streaming, HTTP fallback, and intelligent summarization.

**Module**: croit_log_tools.py
**Classes**: 8 major classes
**Lines**: 2,661
**Type**: Standalone module (optional import)

## Purpose

Provides intelligent log analysis capabilities by:
- Converting natural language queries to structured filters
- Direct VictoriaLogs JSON query execution (no translation layer)
- Binary WebSocket authentication with Croit protocol
- HTTP export fallback for large queries
- Priority-based log summarization
- Critical event extraction
- Server auto-discovery
- Ceph service name translation

## Responsibilities

### 1. Natural Language Intent Parsing
Converts user queries to structured search intents.

### 2. Direct VictoriaLogs JSON Query Execution
No translation layer—LLM writes VictoriaLogs queries directly.

### 3. WebSocket Streaming with Binary Auth
Real-time log streaming with proper Croit authentication.

### 4. HTTP Export Fallback
ZIP-based bulk export for large time ranges.

### 5. Log Summarization
Priority breakdown, critical events, recommendations.

### 6. Server Auto-Discovery
Automatic detection of available server IDs.

### 7. Ceph Service Name Translation
Normalizes service names for accurate queries.

### 8. Debug Template Queries
Pre-built queries for common scenarios.

## Components

### 1. LogSearchIntentParser
Parses natural language into structured intents.

**Key Method**: `parse(search_intent: str) → Dict`

**Capabilities:**
- Pattern detection (OSD issues, slow requests, auth failures, network problems, pool issues)
- Time range extraction ("last hour", "5 minutes ago", "past day")
- Service detection with translation
- Level detection (ERROR, WARN, INFO, DEBUG, all)
- Kernel-specific optimizations
- Performance query handling

**Pattern Recognition:**
- `osd_issues`: OSD failures, flapping, crashes
- `slow_requests`: Slow operations, blocked requests
- `auth_failures`: Authentication errors
- `network_problems`: Connection timeouts, heartbeat issues
- `pool_issues`: Pool full, creation, deletion errors

**Time Parsing:**
- Relative: "last hour", "past 2 days", "recent"
- Ago format: "5 minutes ago", "one hour ago"
- Default: Last hour if not specified

**Output Structure:**
```
{
  "type": "query" | "tail",
  "services": ["ceph-osd@12", "ceph-mon"],
  "levels": ["ERROR", "WARN"],  # Empty list = all levels
  "keywords": ["failed", "timeout"],
  "time_range": {"start": "2024-...", "end": "2024-..."}
}
```

### 2. LogsQLBuilder
Constructs LogsQL queries from parsed intents.

**Key Method**: `build(intent: Dict) → str`

**Query Structure:**
```
_time:[start, end] AND
service:(ceph-osd OR ceph-mon) AND
level:(ERROR OR WARN) AND
_msg:"failed"
```

**Optimization:**
- Time filter first (most selective)
- Service filters second
- Level filters third
- Keyword searches last

### 3. CroitLogSearchClient
Main client for log search operations.

**Key Methods:**
- `search(...)`: Execute log search (WebSocket or HTTP)
- `search_errors(...)`: Priority ≤3 logs
- `search_warnings(...)`: Priority ≤4 logs
- `search_critical(...)`: Priority ≤2 logs
- `search_info(...)`: Priority ≤6 logs
- `discover_servers()`: Auto-detect available servers
- `get_server_summary()`: Human-readable server info
- `analyze_log_transports()`: Kernel log availability
- `find_kernel_logs_debug()`: Kernel log discovery strategies
- `search_optimized(...)`: Auto-truncates for token savings

**Connection Strategies:**
- WebSocket: Real-time streaming (default)
- HTTP Export: Bulk download as ZIP
- Automatic fallback on WebSocket failure

**Caching:**
- 5-minute response cache per query hash
- MD5-based cache keys
- In-memory storage

### 4. CephServiceTranslator
Normalizes Ceph service names for queries.

**Translation Examples:**
- "mon" → "ceph-mon"
- "osd" → "ceph-osd"
- "osd.12" → "ceph-osd@12"
- "mgr" → "ceph-mgr"

**Key Methods:**
- `translate_service_name(name: str) → str`
- `detect_ceph_services_in_text(text: str) → List[str]`

**Pattern Detection:**
- Simple names: "osd", "mon", "mgr", "mds"
- With IDs: "osd.12", "mon.node1"
- With daemons: "osd@12", "mon@node1"
- Full names: "ceph-osd", "ceph-mon"

### 5. CephDebugTemplates
Pre-built query templates for common scenarios.

**Templates:**
- `osd_health_check`: OSD failures, flapping, performance
- `cluster_status_errors`: Critical cluster-wide errors
- `slow_requests`: Slow operations and blocked requests
- `pg_issues`: Placement Group problems
- `network_errors`: Connectivity and heartbeat issues
- `mon_election`: Monitor election problems
- `storage_errors`: Disk errors, SMART failures
- `kernel_ceph_errors`: Kernel-level Ceph messages
- `rbd_mapping_issues`: RBD client problems
- `recent_startup`: Service startup sequences

**Template Structure:**
```
{
  "name": "osd_health_check",
  "description": "Check OSD health...",
  "query": {
    "where": {
      "_and": [
        {"_SYSTEMD_UNIT": {"_contains": "ceph-osd"}},
        {"PRIORITY": {"_lte": 4}}
      ]
    },
    "hours_back": 24,
    "limit": 100
  }
}
```

### 6. ServerIDDetector
Auto-discovers available server IDs from logs.

**Key Methods:**
- `detect_servers(logs: List[Dict]) → Dict`
- `get_activity_level(count: int) → str`

**Detection Logic:**
- Scans `CROIT_SERVER_ID` field in logs
- Counts logs per server
- Extracts hostnames
- Identifies service distribution
- Calculates activity percentages

**Output:**
```
{
  "servers": {
    "1": {
      "id": "1",
      "log_count": 1247,
      "hostnames": ["croit-host-01"],
      "activity_percentage": 45.2,
      "activity_level": "high",
      "services": ["ceph-osd@12", "ceph-mon", ...]
    }
  },
  "total_logs": 2759
}
```

### 7. LogTransportAnalyzer
Analyzes kernel log availability across transports.

**Key Method**: `analyze(logs: List[Dict]) → Dict`

**Transport Types:**
- `kernel`: Direct kernel messages
- `syslog`: Syslog-forwarded kernel messages
- `journal`: Systemd journal kernel messages

**Analysis Output:**
```
{
  "transports": {
    "kernel": {
      "count": 145,
      "percentage": 5.2,
      "sample_messages": [...]
    }
  },
  "has_kernel_logs": true,
  "kernel_log_percentage": 5.2,
  "recommendations": [...]
}
```

### 8. LogSummaryEngine
Generates intelligent log summaries with critical event extraction.

**Key Methods:**
- `generate_summary(logs: List[Dict]) → Dict`
- `extract_critical_events(logs: List[Dict], top_n: int) → List[Dict]`
- `generate_recommendations(summary: Dict) → List[str]`

**Summary Components:**
1. **Priority Breakdown**: Count by log level
2. **Service Breakdown**: Count by service name
3. **Critical Events**: Top N most critical (scored)
4. **Trends**: Peak hours, busiest services
5. **Recommendations**: Actionable guidance

**Critical Event Scoring:**
- Priority weight: ERROR=-10, WARN=-5, INFO=0
- Keyword penalties: "fail"=-3, "timeout"=-2
- Sorts by score (lower = more critical)

**Recommendation Logic:**
- 5+ critical events → "Immediate attention needed"
- Multiple OSD issues → "Check storage health"
- Network timeouts → "Investigate network"
- Authentication failures → "Review access controls"

## Data Flow

### Log Search Execution

```
User Query (natural language)
    ↓
LogSearchIntentParser.parse()
    ↓
LogsQLBuilder.build()  OR  Direct JSON Query
    ↓
CroitLogSearchClient.search()
    ├─→ WebSocket Path
    │   ├── Binary auth token
    │   ├── Send JSON query
    │   ├── Receive control messages
    │   └── Stream log entries
    └─→ HTTP Export Path (fallback)
        ├── POST to /api/log/export
        ├── Download ZIP file
        └── Extract logs from archive
    ↓
Response Processing
    ├── ServerIDDetector.detect_servers()
    ├── LogTransportAnalyzer.analyze()
    └── LogSummaryEngine.generate_summary()
    ↓
Optimized Response
    ├── Truncate to 50 logs (if needed)
    ├── Shorten messages to 150 chars
    └── Prioritize critical events
    ↓
Return to LLM
```

### WebSocket Protocol

```
Connection
    ↓
Send Binary Auth Token
    ↓
Send JSON Query
{
  "where": {...},
  "hours_back": 24,
  "limit": 1000,
  "_search": "optional text search"
}
    ↓
Receive Control Messages
    ├── "empty" → No logs found
    ├── "too_wide" → Time range too large
    ├── "hits: N" → Result count
    └── "error: msg" → Error occurred
    ↓
Receive Log Entries (JSON stream)
    ↓
Process and Return
```

## Performance Characteristics

**WebSocket Performance:**
- Connection setup: <500ms
- Streaming throughput: ~1000 logs/second
- Memory: Buffers all logs in memory

**HTTP Export Performance:**
- Request time: 2-10s (depending on log count)
- ZIP extraction: ~1s per 10,000 logs
- Memory: Entire ZIP in memory

**Caching:**
- Cache hit: <1ms
- Cache duration: 5 minutes
- No cache invalidation (TTL only)

**Summarization:**
- 1,000 logs: ~50ms
- 10,000 logs: ~500ms
- 100,000 logs: ~5s (with optimization)

## VictoriaLogs Query Syntax

**Supported Operators:**
- **String**: `_eq`, `_contains`, `_starts_with`, `_ends_with`, `_regex`
- **Numeric**: `_eq`, `_neq`, `_gt`, `_gte`, `_lt`, `_lte`
- **List**: `_in`, `_nin`
- **Logic**: `_and`, `_or`, `_not`
- **Existence**: `_exists`, `_missing`

**Common Fields:**
- `_SYSTEMD_UNIT`: Service name (e.g., "ceph-osd@12")
- `PRIORITY`: Log level (0=EMERGENCY, 3=ERROR, 4=WARNING, 6=INFO)
- `CROIT_SERVER_ID`: Server identifier
- `_TRANSPORT`: Log source (kernel/syslog/journal)
- `_HOSTNAME`: System hostname
- `MESSAGE`: Log message text
- `_search`: Full-text search

## Integration with MCP Server

**Tool Registration:**
Tools added via `_add_log_search_tools()`:
- `croit_log_search`: Main search interface
- `croit_log_check`: Condition checking
- `croit_log_monitor`: Live monitoring

**Handler Functions:**
- `handle_log_search(host, token, arguments)`
- `handle_log_check(host, token, arguments)`
- `handle_log_monitor(host, token, arguments)`

**Error Handling:**
- WebSocket failures → HTTP fallback
- Connection timeouts → Retry with backoff
- Invalid queries → Error message to LLM

## Design Patterns

**Strategy Pattern**: WebSocket vs HTTP execution paths
**Builder Pattern**: LogsQLBuilder constructs queries
**Parser Pattern**: Intent parsing with pattern matching
**Template Pattern**: Debug templates
**Facade Pattern**: CroitLogSearchClient simplifies complexity

## Extension Points

1. **New Patterns**: Add to `LogSearchIntentParser.PATTERNS`
2. **New Templates**: Extend `CephDebugTemplates.TEMPLATES`
3. **Custom Summarization**: Modify `LogSummaryEngine` methods
4. **Additional Transports**: Extend `LogTransportAnalyzer`
5. **Service Translations**: Add to `CephServiceTranslator` patterns

## Relevance

Read this document when:
- Understanding log search capabilities
- Implementing new search patterns
- Debugging VictoriaLogs integration
- Optimizing log query performance
- Adding new debug templates
- Troubleshooting WebSocket issues

## Related Documentation

- [ARCHITECTURE.intent-parsing.md](ARCHITECTURE.intent-parsing.md) - Intent parsing details
- [ARCHITECTURE.victorialogs-websocket-protocol.md](ARCHITECTURE.victorialogs-websocket-protocol.md) - WebSocket protocol
- [ARCHITECTURE.service-name-translation.md](ARCHITECTURE.service-name-translation.md) - Service translation
- [ARCHITECTURE.log-search-execution.md](ARCHITECTURE.log-search-execution.md) - Execution flow
- [ARCHITECTURE.ceph-debug-templates.md](ARCHITECTURE.ceph-debug-templates.md) - Template details
