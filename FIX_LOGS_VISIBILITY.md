# Problem: Logs Endpoint nicht sichtbar in Hybrid Mode

## Analyse
- `/logs/export` existiert und hat x-llm-hints
- Kategorie "logs" hat nur 1 Endpoint
- Rang #40 von allen Kategorien → nicht in Top 10
- Hybrid Mode zeigt nur Top 10 Kategorien

## Lösungsoptionen

### Option 1: Logs zur "stats" Kategorie hinzufügen
Da "stats" bereits in den Top 10 ist (Rang #10), könnte man `/logs/export` zusätzlich mit dem "stats" Tag versehen.

### Option 2: Explizite Logs-Unterstützung im MCP Script
Modifiziere mcp-croit-ceph.py um wichtige einzelne Endpoints einzuschließen:

```python
# In _generate_hybrid_tools() nach der Top 10 Auswahl:

# Always include critical single endpoints regardless of category rank
CRITICAL_ENDPOINTS = [
    ('logs', 'export'),  # /logs/export
    ('osds', 'destroy'), # wichtige OSD operations
]

for category, keyword in CRITICAL_ENDPOINTS:
    if category in self.category_endpoints:
        for endpoint in self.category_endpoints[category]:
            if keyword.lower() in endpoint['path'].lower():
                # Add this endpoint to selected categories
                if category not in selected_categories:
                    selected_categories[category] = self.category_endpoints[category]
```

### Option 3: Max Category Tools erhöhen
Einfachste Lösung: Default von 10 auf 15-20 erhöhen:

```python
# In mcp-croit-ceph.py
def __init__(self, ..., max_category_tools=15):  # statt 10
```

### Option 4: Logs-spezifisches Base Tool
Füge ein dediziertes "query_logs" Tool zu den Base Tools hinzu:

```python
def _generate_base_tools(self):
    # Existing tools...

    # Add dedicated logs tool
    self.mcp_tools.append(
        types.Tool(
            name="query_logs",
            description="Query and export system logs. Use format='json' for structured data.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "object",
                        "description": "LogsQL query with filters and time range",
                        "properties": {
                            "type": {"type": "string", "enum": ["tail", "query"]},
                            "start": {"type": "integer", "description": "Start timestamp"},
                            "end": {"type": "integer", "description": "End timestamp"},
                            "filter": {"type": "string", "description": "LogsQL filter expression"}
                        }
                    },
                    "format": {
                        "type": "string",
                        "enum": ["json", "raw", "cat", "short"],
                        "default": "json"
                    }
                }
            }
        )
    )
```

## Empfehlung

**Kurzfristig (sofort)**: Option 3 - max_category_tools auf 15 erhöhen
```bash
# In Claude Desktop Config oder Docker:
--max-category-tools 15
```

**Mittelfristig**: Option 2 - Critical endpoints immer einschließen

**Langfristig**: Option 1 - OpenAPI spec anpassen, logs mit stats oder monitoring taggen