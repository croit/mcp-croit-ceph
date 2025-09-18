# Token-Optimierung für MCP Croit Ceph

## Problem
- Viele Endpoints returnen große Datenmengen (100+ Objekte)
- LLMs verbrauchen schnell Token-Limits
- Nur 5 von 580 Endpoints haben Pagination-Parameter

## Lösungsansätze

### 1. Intelligente Default-Limits im MCP Server

```python
# In mcp-croit-ceph.py

DEFAULT_RESPONSE_LIMITS = {
    # Pattern-based limits
    'list': 10,      # Für alle List-Operations
    'get_all': 20,   # Für GetAll operations
    'stats': 50,     # Für Stats (mehr Details ok)
    'logs': 100,     # Für Logs (neueste 100)
    'export': 1000,  # Export kann mehr haben
}

def _add_smart_defaults(self, parameters, operation, path):
    """Add intelligent default limits to prevent token overflow"""

    summary = operation.get('summary', '').lower()

    # Auto-add limit parameter if missing
    if 'limit' not in [p.get('name') for p in operation.get('parameters', [])]:
        # Determine appropriate default
        default_limit = 25

        for pattern, limit in DEFAULT_RESPONSE_LIMITS.items():
            if pattern in summary or pattern in path.lower():
                default_limit = limit
                break

        # Inject limit parameter
        if 'properties' not in parameters['input_schema']:
            parameters['input_schema']['properties'] = {}

        parameters['input_schema']['properties']['_auto_limit'] = {
            'type': 'integer',
            'default': default_limit,
            'description': f'Auto-added limit to prevent token overflow (default: {default_limit})'
        }
```

### 2. Response Truncation mit Hinweis

```python
def _truncate_response(self, response_data, max_items=50):
    """Truncate large responses with summary"""

    if isinstance(response_data, list) and len(response_data) > max_items:
        truncated = response_data[:max_items]
        return {
            'data': truncated,
            '_truncated': True,
            '_total_count': len(response_data),
            '_returned_count': max_items,
            '_message': f'Response truncated from {len(response_data)} to {max_items} items to save tokens. Use pagination or filters to get specific items.'
        }

    return response_data
```

### 3. Feld-Filterung (Projection)

```python
ESSENTIAL_FIELDS = {
    'servers': ['id', 'hostname', 'ip', 'status'],
    'services': ['id', 'type', 'status', 'hostname'],
    'osds': ['id', 'status', 'host', 'used_percent'],
    'pools': ['name', 'id', 'size', 'used_bytes'],
}

def _add_field_filter(self, tool_description, category):
    """Add field filtering hints to tool description"""

    if category in ESSENTIAL_FIELDS:
        tool_description += f"""

Token Optimization Tips:
- Default returns only essential fields: {ESSENTIAL_FIELDS[category]}
- Use 'fields=*' to get all fields
- Use 'fields=id,name,status' to get specific fields
- Use 'limit=10' to reduce results
"""
```

### 4. Erweiterte x-llm-hints

In der OpenAPI spec sollten wir hinzufügen:

```yaml
x-llm-hints:
  response_size: "large"  # small/medium/large/huge
  default_limit: 10
  recommended_fields: ["id", "name", "status"]
  token_estimate: 500  # Estimated tokens per item
  optimization_tips:
    - "Use limit=10 for initial exploration"
    - "Filter by status='error' for troubleshooting"
    - "Use fields=id,name for minimal response"
```

### 5. Zusammenfassungs-Tool

Neues Base-Tool für große Datensätze:

```python
def _add_summary_tool(self):
    """Add tool for summarizing large responses"""

    self.mcp_tools.append(
        types.Tool(
            name="summarize_response",
            description="Get a summary of a large dataset instead of full data",
            inputSchema={
                "type": "object",
                "properties": {
                    "endpoint": {"type": "string", "description": "The endpoint to call"},
                    "summary_type": {
                        "type": "string",
                        "enum": ["count", "stats", "errors_only", "changes_only"],
                        "default": "stats"
                    },
                    "group_by": {
                        "type": "string",
                        "description": "Field to group results by"
                    }
                }
            }
        )
    )
```

### 6. Streaming/Progressive Loading

```python
def _add_progressive_hints(self, tool_description):
    """Add hints about progressive data loading"""

    return tool_description + """

For large datasets:
1. First call with limit=1 to see structure
2. Then limit=10 to see patterns
3. Use filters to narrow down
4. Only fetch full data if needed
"""
```

## Implementierungs-Priorität

### Sofort (Quick Win)
1. **Default Limits** - Automatisch limit=25 für alle List-Operations
2. **Response Truncation** - Bei >50 Items automatisch kürzen

### Kurzfristig
3. **Smart Descriptions** - Token-Spar-Tipps in Tool-Beschreibungen
4. **Field Filtering** - Nur essentielle Felder standardmäßig

### Mittelfristig
5. **Summary Tool** - Aggregierte Daten statt Rohdaten
6. **OpenAPI Hints** - response_size und token_estimate in x-llm-hints

## Beispiel-Implementation

```python
# In mcp-croit-ceph.py beim Tool-Call

async def call_tool(self, name: str, arguments: Dict) -> Any:
    # ... existing code ...

    # Auto-add limit if not specified
    if 'list' in name.lower() or 'get_all' in name.lower():
        if 'limit' not in arguments and 'limit' not in url_params:
            url_params['limit'] = 25
            logger.info(f"Auto-added limit=25 to {name} to prevent token overflow")

    # Make API call
    response = await self._make_api_call(...)

    # Truncate if needed
    if isinstance(response, list) and len(response) > 50:
        logger.warning(f"Truncating response from {len(response)} to 50 items")
        response = response[:50]
        response = {
            'data': response,
            '_note': 'Response truncated to save tokens. Use pagination for more.'
        }

    return response
```