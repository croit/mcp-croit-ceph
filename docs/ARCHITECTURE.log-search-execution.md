# Log Search Execution

## Overview

The log search execution workflow processes natural language queries through intent parsing, VictoriaLogs query execution, and intelligent summarization. It supports dual-path execution (WebSocket/HTTP) with automatic fallback.

**Module**: croit_log_tools.py
**Functions**: `handle_log_search()`, `_execute_croit_websocket()`, `_execute_croit_http_export()`
**Duration**: 500ms - 10s depending on query scope

## Purpose

Executes log searches with:
- Natural language to structured query conversion
- Direct VictoriaLogs JSON query support
- Dual-path execution (WebSocket preferred, HTTP fallback)
- Response summarization and optimization
- Critical event extraction

## Execution Paths

### Path Selection Logic

```
User Query
    ↓
Is Direct JSON Query?
├── Yes → Skip intent parsing
└── No → Parse with LogSearchIntentParser
    ↓
Execution Strategy Selection
├── Small query (< 1000 logs expected) → WebSocket
└── Large query (> 1000 logs) → HTTP Export
    ↓
Try WebSocket
├── Success → Return results
└── Failure → Fall back to HTTP Export
```

## Complete Workflow

### Phase 1: Intent Parsing (Optional)

**Condition**: Query is natural language, not JSON

**Method**: `LogSearchIntentParser.parse(search_intent)`

```
Input: "Find OSD errors in the last hour"
    ↓
Pattern Detection
├── Detect "OSD" → services: ["ceph-osd"]
├── Detect "errors" → levels: ["ERROR"]
└── Detect "last hour" → time_range
    ↓
Service Translation
└── "OSD" → "ceph-osd"
    ↓
Output: {
  "type": "query",
  "services": ["ceph-osd"],
  "levels": ["ERROR"],
  "keywords": ["failed", "error"],
  "time_range": {"start": "...", "end": "..."}
}
```

### Phase 2: Query Building

**Two paths**:

#### A. From Intent (Natural Language)
**Method**: `LogsQLBuilder.build(intent)`

```
intent → LogsQL string

Example:
_time:[2024-01-01T00:00:00Z, 2024-01-01T01:00:00Z] AND
service:(ceph-osd) AND
level:(ERROR) AND
_msg:"failed"
```

#### B. Direct JSON (Advanced)
**User provides VictoriaLogs JSON directly**:

```json
{
  "where": {
    "_and": [
      {"_SYSTEMD_UNIT": {"_contains": "ceph-osd"}},
      {"PRIORITY": {"_lte": 3}}
    ]
  },
  "hours_back": 1,
  "limit": 1000
}
```

### Phase 3: WebSocket Execution

**Method**: `_execute_croit_websocket()`

```
Step 1: Connection Establishment
├── Connect to wss://{host}/api/log/websocket
├── SSL verification based on protocol
└── Connection timeout: 30s

Step 2: Binary Authentication
├── Send API token as binary message
└── Wait for acknowledgment

Step 3: Query Transmission
├── Convert query to JSON
├── Add current timestamp context
├── Send as text message

Step 4: Control Message Processing
├── "empty" → No logs found
├── "too_wide" → Time range too large
├── "hits: N" → Result count
└── "error: msg" → Error occurred

Step 5: Log Entry Streaming
├── Receive JSON log entries
├── Parse and accumulate
├── Track progress
└── Handle connection drops

Step 6: Completion
└── Connection closes → Return accumulated logs
```

**Error Conditions**:
- Connection timeout → Fall back to HTTP
- Authentication failure → Raise error
- "too_wide" control message → Suggest narrower range
- WebSocket error → Fall back to HTTP

### Phase 4: HTTP Export Execution (Fallback)

**Method**: `_execute_croit_http_export()`

```
Step 1: Build Export Request
├── POST to /api/log/export
├── Body: VictoriaLogs JSON query
└── Headers: Authorization, Accept

Step 2: Download ZIP Archive
├── Response: application/zip
├── Read into memory
└── Size can be 1MB - 100MB+

Step 3: Extract Logs
├── Open ZIP in memory
├── Read logs.json file
├── Parse JSON array
└── Extract log entries

Step 4: Return Results
└── Same format as WebSocket path
```

**Advantages over WebSocket**:
- Handles large result sets
- Reliable for bulk operations
- No streaming complexity

**Disadvantages**:
- Slower (2-10s vs 500ms-2s)
- Higher memory usage
- No progress updates

### Phase 5: Response Processing

#### Server Auto-Discovery
**Method**: `ServerIDDetector.detect_servers(logs)`

```
Scan logs for CROIT_SERVER_ID field
    ↓
Group by server ID
    ↓
Extract:
├── Server ID
├── Hostnames
├── Log counts
├── Activity percentages
└── Service distribution
```

#### Transport Analysis
**Method**: `LogTransportAnalyzer.analyze(logs)`

```
Scan logs for _TRANSPORT field
    ↓
Count by transport type:
├── kernel: Direct kernel messages
├── syslog: Syslog-forwarded
└── journal: Systemd journal
    ↓
Calculate percentages and provide samples
```

#### Summarization
**Method**: `LogSummaryEngine.generate_summary(logs)`

```
Step 1: Priority Breakdown
└── Count by PRIORITY field (0-7)

Step 2: Service Breakdown
└── Count by _SYSTEMD_UNIT field

Step 3: Critical Event Extraction
├── Score each log entry
│   ├── Priority weight (ERROR=-10, WARN=-5)
│   ├── Keyword penalties (fail=-3, timeout=-2)
│   └── Sort by score (lower = more critical)
└── Extract top N events

Step 4: Trend Analysis
├── Group logs by hour
├── Identify peak periods
└── Find busiest services

Step 5: Recommendations
├── Check for patterns
└── Generate actionable guidance
```

#### Response Optimization
**Method**: `CroitLogSearchClient.optimize_response_size()`

```
If optimize_response=True:
├── Truncate to max_log_entries (default: 50)
├── Shorten messages to max_message_length (default: 150)
├── Prioritize critical events
└── Add truncation metadata
```

### Phase 6: Result Assembly

**Complete Response Structure**:
```python
{
  "logs": [...],  # Log entries (possibly truncated)
  "total_count": 1247,
  "returned_count": 50,
  "summary": {
    "priority_breakdown": {...},
    "service_breakdown": {...},
    "critical_events": [...],
    "trends": {...},
    "recommendations": [...]
  },
  "server_info": {...},  # Auto-discovered servers
  "transport_analysis": {...},  # If kernel logs requested
  "query_info": {
    "execution_method": "websocket|http_export",
    "execution_time_ms": 1234,
    "cache_hit": false
  },
  "_optimization_applied": true,  # If truncated
  "_truncation_metadata": {...}  # If truncated
}
```

## Query Examples

### Natural Language Queries

**OSD Issues**:
```
Input: "Find OSD failures in the last 24 hours"
→ services: ["ceph-osd"]
→ levels: ["ERROR", "CRITICAL"]
→ keywords: ["failed", "down", "crashed"]
→ hours_back: 24
```

**Slow Requests**:
```
Input: "Show slow requests in the past hour"
→ keywords: ["slow request", "blocked"]
→ services: ["ceph-osd", "ceph-mon", "ceph-mds"]
→ levels: ["WARN", "ERROR"]
→ hours_back: 1
```

**Kernel Logs**:
```
Input: "Get kernel errors related to Ceph"
→ transport: "kernel"
→ levels: ["ERROR", "WARNING"]
→ keywords: ["ceph"]
```

### Direct JSON Queries

**Monitor Logs on Server 1**:
```json
{
  "where": {
    "_and": [
      {"_SYSTEMD_UNIT": {"_contains": "ceph-mon"}},
      {"CROIT_SERVER_ID": {"_eq": "1"}},
      {"PRIORITY": {"_lte": 6}}
    ]
  },
  "hours_back": 24
}
```

**Kernel Errors with Text Search**:
```json
{
  "where": {
    "_and": [
      {"_TRANSPORT": {"_eq": "kernel"}},
      {"PRIORITY": {"_lte": 4}}
    ]
  },
  "_search": "error",
  "hours_back": 48
}
```

## Caching Strategy

**Cache Key Generation**:
```python
query_hash = hashlib.md5(json.dumps(query, sort_keys=True).encode()).hexdigest()
```

**Cache Lookup**:
```python
if query_hash in cache and cache_age < 5 minutes:
    return cached_result
```

**Cache Population**:
```python
cache[query_hash] = {
    "result": response,
    "timestamp": datetime.now()
}
```

**Cache Invalidation**:
- Time-based: 5 minute TTL
- No manual invalidation
- No size limits (in-memory only)

## Performance Characteristics

**WebSocket Path**:
- Connection: 200-500ms
- Streaming: 50-200ms per 100 logs
- Small query (< 100 logs): 500-1000ms total
- Medium query (100-1000 logs): 1-3s total
- Large query (> 1000 logs): Falls back to HTTP

**HTTP Export Path**:
- Request: 1-5s
- ZIP download: 1-10s (size dependent)
- Extraction: 0.5-2s
- **Total**: 2-17s

**Summarization**:
- 100 logs: <50ms
- 1,000 logs: 100-300ms
- 10,000 logs: 1-3s

## Error Handling

**Query Errors**:
- Invalid syntax → Parse error to LLM
- Invalid field names → VictoriaLogs error to LLM
- Too wide time range → "too_wide" message to LLM

**Connection Errors**:
- WebSocket timeout → Fall back to HTTP
- HTTP failure → Raise error to LLM
- Authentication failure → Auth error to LLM

**Data Processing Errors**:
- Invalid JSON → Logged, empty result
- Missing fields → Use defaults
- Corrupt ZIP → Raise error

## Design Patterns

**Strategy Pattern**: WebSocket vs HTTP execution
**Chain of Responsibility**: Fallback mechanism
**Template Method**: Common processing structure
**Builder Pattern**: Query construction
**Observer Pattern**: Streaming log reception

## Extension Points

1. **New Query Patterns**: Extend LogSearchIntentParser.PATTERNS
2. **Custom Summarization**: Modify LogSummaryEngine
3. **Additional Transports**: Extend transport analysis
4. **Caching Strategies**: Replace in-memory cache
5. **Execution Paths**: Add new execution methods

## Relevance

Read this document when:
- Understanding log search flow
- Debugging query issues
- Implementing new search patterns
- Optimizing log search performance
- Troubleshooting WebSocket issues
- Understanding summarization logic

## Related Documentation

- [ARCHITECTURE.log-search-system.md](ARCHITECTURE.log-search-system.md) - System overview
- [ARCHITECTURE.intent-parsing.md](ARCHITECTURE.intent-parsing.md) - Intent parsing
- [ARCHITECTURE.victorialogs-websocket-protocol.md](ARCHITECTURE.victorialogs-websocket-protocol.md) - WebSocket protocol
- [ARCHITECTURE.log-summary-engine.md](ARCHITECTURE.log-summary-engine.md) - Summarization
