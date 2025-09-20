# Croit MCP Server - Architecture Documentation

## System Overview

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   LLM Client    │────▶│   MCP Server     │────▶│  Croit Cluster  │
│    (Claude)     │◀────│ (mcp-croit-ceph) │◀────│   API + Logs    │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │
                    ┌──────────┴──────────┐
                    │                     │
            ┌───────▼────────┐   ┌───────▼────────┐
            │  API Handler   │   │  Log Handler   │
            │  (OpenAPI)     │   │  (WebSocket)   │
            └────────────────┘   └────────────────┘
```

## Core Components

### 1. Main Server (`mcp-croit-ceph.py`)

**Class: CroitCephServer**
- Dynamically loads OpenAPI spec from Croit cluster
- Generates MCP tools from API endpoints
- Handles authentication and API calls
- Manages different operating modes

**Key Features:**
- **Dynamic tool generation** from OpenAPI spec with full x-llm-hints
- **Smart search prioritization** - Most relevant endpoints first
- **Intent-based filtering** - read/write/manage operations
- **Feature flags** - Disable DAOS/specialty tools to reduce token usage
- **Direct VictoriaLogs integration** - No translation layer
- **Real-time log streaming** with proper WebSocket authentication
- **Comprehensive error handling** and MCP protocol compliance
- **Token optimization** - Up to 90% reduction in common searches

### 2. Token Optimizer (`token_optimizer.py`)

**Purpose:** Reduces token usage by filtering and truncating responses

**Optimization Strategies:**
- Automatic pagination limits
- Response truncation for large datasets
- Field filtering for verbose responses
- Smart defaults for common queries

**Key Methods:**
- `should_optimize(url, method)`: Determines if optimization needed
- `add_default_limit(params)`: Adds reasonable limits
- `truncate_response(data)`: Limits response size
- `apply_filters(data, filters)`: Applies user filters

### 3. Log Search Tools (`croit_log_tools.py`)

**Revolutionary Direct VictoriaLogs Integration:**

#### Direct JSON Query Interface
- **No translation layer** - LLM writes VictoriaLogs JSON directly
- **Full VictoriaLogs power** - All operators and fields supported
- **Binary WebSocket authentication** - Correct Croit protocol implementation
- **Control message handling** - "empty", "too_wide", "hits:", "error:" responses

#### Comprehensive Operator Support
- **String operators:** `_eq`, `_contains`, `_starts_with`, `_ends_with`, `_regex`
- **Numeric operators:** `_eq`, `_neq`, `_gt`, `_gte`, `_lt`, `_lte`
- **List operators:** `_in`, `_nin`
- **Logical operators:** `_and`, `_or`, `_not`
- **Existence operators:** `_exists`, `_missing`

#### Complete Field Coverage
- **Core fields:** `_SYSTEMD_UNIT`, `PRIORITY`, `CROIT_SERVER_ID`, `MESSAGE`
- **Transport:** `_TRANSPORT` (kernel/syslog/journal)
- **System fields:** `_HOSTNAME`, `_MACHINE_ID`, `SYSLOG_IDENTIFIER`, `THREAD`
- **Search:** `_search` for full-text search

## Data Flow

### API Calls
```
1. LLM invokes tool with arguments
2. Server validates and builds request
3. Token optimizer adds limits
4. HTTPS request to Croit API
5. Response filtering and truncation
6. Return structured result to LLM
```

### Log Searches (Direct VictoriaLogs)
```
1. LLM provides VictoriaLogs JSON query directly
2. Server adds current time context automatically
3. WebSocket connection with binary auth token
4. Query sent as structured JSON to Croit
5. Control messages handled ("empty", "too_wide", etc.)
6. Log entries and metadata returned
7. Debug info shows exact query sent
```

## Operating Modes

### Hybrid Mode (Default)
```python
mode="hybrid"
```
- Base tools (list, call, schema)
- Category-specific tools
- Best balance of flexibility and organization

### Base Only Mode
```python
mode="base_only"
```
- Minimal tool set
- Maximum flexibility
- Direct API endpoint access

### Categories Only Mode
```python
mode="categories_only"
```
- Organized by functional area
- Easier discovery
- More guided experience

### Endpoints as Tools Mode
```python
mode="endpoints_as_tools"
```
- Every endpoint becomes a tool
- Maximum granularity
- Can be overwhelming

## Authentication

### API Token
```bash
--api-token YOUR_TOKEN
```
- Bearer token authentication
- Passed in Authorization header
- Required for all API calls

### Environment Variables
```bash
CROIT_API_TOKEN=your_token
CROIT_HOST=cluster.example.com:8080
```

## WebSocket Protocol

### Connection
```python
ws://host:8080/api/logs
Headers: {
    "Authorization": "Bearer TOKEN"
}
```

### Message Format
```json
{
  "type": "query|tail",
  "query": {
    "where": "LogsQL filter",
    "limit": 1000
  },
  "start": "ISO8601",
  "end": "ISO8601"
}
```

### Response Stream
```json
{
  "timestamp": "2024-01-01T12:00:00Z",
  "message": "Log message",
  "level": "ERROR",
  "service": "ceph-osd",
  "host": "node1",
  "metadata": {}
}
```

## Caching Strategy

### Query Cache
- 5-minute TTL for identical queries
- MD5 hash for cache keys
- Automatic invalidation on errors

### Results Cache
- In-memory storage
- Limited to recent queries
- Cleared on connection errors

## Error Handling

### Graceful Degradation
```
WebSocket Failed → HTTP Fallback
HTTP Failed → Cached Results
Cache Miss → Error with context
```

### Retry Logic
- WebSocket: No retry, immediate fallback
- HTTP: Single retry with backoff
- Cache: Always check before external call

## Performance Optimizations

### Query Optimization
1. Time filters applied first
2. Service-specific indexes used
3. Limit parameters added automatically
4. Selective field retrieval

### Response Optimization
1. Pagination with reasonable defaults
2. Field filtering for large objects
3. Response truncation at 30KB
4. Streaming for large datasets

## Pattern Detection Algorithms

### Error Clustering
```python
1. Normalize messages (remove numbers, IDs)
2. Group by similarity threshold
3. Count occurrences
4. Identify top patterns
```

### Burst Detection
```python
1. Group logs by time window (1 minute)
2. Calculate volume per window
3. Identify statistical outliers
4. Mark as burst if > threshold
```

### Correlation Analysis
```python
1. Identify primary event
2. Find events in time window
3. Calculate temporal distance
4. Group by service
5. Score correlation confidence
```

## Docker Deployment

### Image Structure
```dockerfile
FROM python:3.13-slim
├── requirements.txt      # Dependencies
├── mcp-croit-ceph.py    # Main server
├── token_optimizer.py   # Optimization module
└── croit_log_tools.py   # Log search tools
```

### Runtime Configuration
```bash
docker run -e CROIT_HOST=cluster:8080 \
           -e CROIT_API_TOKEN=token \
           ghcr.io/croit/mcp-croit-ceph
```

## Security Considerations

### Token Management
- Never log tokens
- Environment variable preferred
- Secure transmission only
- Token rotation supported

### Data Filtering
- Sensitive data detection
- PII removal options
- Audit log separation
- Role-based filtering

## Monitoring & Debugging

### Debug Mode
```bash
export LOG_LEVEL=DEBUG
python mcp-croit-ceph.py --debug
```

### Metrics Tracked
- Query count and latency
- Cache hit rate
- WebSocket connection stability
- Error rates by type

### Log Locations
- Application logs: stderr
- MCP protocol: stdio
- Debug output: LOG_LEVEL=DEBUG

## Extension Points

### Adding New Patterns
```python
LogSearchIntentParser.PATTERNS['new_pattern'] = {
    'regex': r'pattern',
    'services': ['service'],
    'levels': ['ERROR'],
    'keywords': ['keyword']
}
```

### Custom Filters
```python
def custom_filter(data):
    # Filter implementation
    return filtered_data
```

### New Tool Categories
```python
self.category_tools['new_category'] = {
    'tool_name': tool_definition
}
```

## Testing

### Unit Tests
```bash
python -m pytest tests/
```

### Integration Tests
```bash
docker-compose up -d
python tests/integration.py
```

### Load Testing
```bash
locust -f tests/load.py --host http://cluster:8080
```

## Limitations

### WebSocket
- 30-second timeout per query
- 1MB message size limit
- Single connection per query

### Caching
- In-memory only (no persistence)
- 5-minute TTL (not configurable)
- Limited to 100 cached queries

### Response Size
- 30KB truncation limit
- 100 logs maximum in response
- 20 patterns per analysis

## Recent Major Improvements (2024)

### Search & Discovery Revolution
1. **Smart Prioritization** - Ceph pools prioritized over DAOS pools
2. **Intent-based filtering** - Filter by read/write/manage operations
3. **Multi-word search** - "create rbd" matches "Create a new RBD"
4. **Feature flags** - Disable unused endpoints for token savings
5. **Quick-find tool** - Instant access to common categories

### VictoriaLogs Integration
1. **Direct JSON interface** - No translation layer complexity
2. **Binary WebSocket auth** - Correct Croit protocol implementation
3. **Full operator support** - _eq, _neq, _regex, _in, _nin, etc.
4. **Control message handling** - "empty", "too_wide", error feedback
5. **Real-time context** - Current timestamps injected automatically
6. **Comprehensive field support** - All Ceph/system fields documented

### Token Optimization Achievements
- **Search optimization:** 89% reduction for targeted searches
- **Feature filtering:** 16.9% overall endpoint reduction
- **Smart truncation:** Priority results shown first
- **Intent filtering:** 59-85% reduction per operation type

## Future Enhancements

### Planned Features
1. VictoriaMetrics integration for performance data
2. Log+Metrics correlation analysis
3. Multi-cluster support
4. Custom alert definitions
5. Grafana dashboard integration