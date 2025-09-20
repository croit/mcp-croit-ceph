#!/usr/bin/env python3
"""
Croit Log Intelligence Tools for MCP Server
Provides advanced log search and analysis capabilities
"""

import json
import asyncio
import websockets
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import re
import hashlib
from collections import defaultdict
import aiohttp

logger = logging.getLogger(__name__)

class LogSearchIntentParser:
    """Parse natural language into structured search intents"""

    PATTERNS = {
        'osd_issues': {
            'regex': r'(osd|OSD|object.?storage).*?(fail|down|crash|slow|error|flap|timeout)',
            'services': ['ceph-osd', 'ceph-mon'],
            'levels': ['ERROR', 'WARN', 'FATAL'],
            'keywords': ['OSD', 'failed', 'down', 'crashed', 'flapping']
        },
        'slow_requests': {
            'regex': r'(slow|blocked|stuck|delayed)\s+(request|operation|op|query|io)',
            'services': ['ceph-osd', 'ceph-mon', 'ceph-mds'],
            'levels': ['WARN', 'ERROR'],
            'keywords': ['slow request', 'blocked', 'timeout', 'stuck']
        },
        'auth_failures': {
            'regex': r'(auth|authentication|login|permission).*?(fail|denied|error)',
            'services': ['ceph-mon', 'ceph-mgr'],
            'levels': ['ERROR', 'WARN'],
            'keywords': ['authentication', 'failed', 'denied', 'unauthorized']
        },
        'network_problems': {
            'regex': r'(network|connection|timeout|unreachable|heartbeat|msgr)',
            'services': ['ceph-mon', 'ceph-osd', 'ceph-mds', 'ceph-mgr'],
            'levels': ['ERROR', 'WARN'],
            'keywords': ['connection', 'timeout', 'network', 'unreachable', 'heartbeat']
        },
        'pool_issues': {
            'regex': r'pool.*?(full|create|delete|error)',
            'services': ['ceph-mon', 'ceph-mgr'],
            'levels': ['ERROR', 'WARN'],
            'keywords': ['pool', 'full', 'quota', 'space']
        }
    }

    def parse(self, search_intent: str) -> Dict[str, Any]:
        """Parse natural language search intent"""
        intent = search_intent.lower()

        # Detect patterns
        detected_patterns = []
        for pattern_name, pattern_def in self.PATTERNS.items():
            if re.search(pattern_def['regex'], intent, re.IGNORECASE):
                detected_patterns.append(pattern_name)

        # Extract components
        services = set()
        levels = set()
        keywords = set()

        for pattern_name in detected_patterns:
            pattern = self.PATTERNS[pattern_name]
            services.update(pattern['services'])
            levels.update(pattern['levels'])
            keywords.update(pattern['keywords'])

        # Check for explicit level requests in text
        intent_lower = intent.lower()
        if 'all level' in intent_lower or 'all log' in intent_lower or 'everything' in intent_lower:
            # User wants all log levels - clear any pattern-based filters
            levels = set()
        elif 'info' in intent_lower and 'info' not in ' '.join(keywords).lower():
            levels.add('INFO')
        elif 'debug' in intent_lower:
            levels.add('DEBUG')
        elif 'trace' in intent_lower:
            levels.add('TRACE')

        # Only default to ERROR/WARN if user is explicitly looking for problems
        # If no levels set and no explicit problem words, return all levels
        if not levels and not any(word in intent_lower for word in ['error', 'fail', 'problem', 'issue', 'crash', 'wrong']):
            levels = set()  # Empty means no filter - get all levels

        # Parse time range
        time_range = self._parse_time_range(intent)

        # Determine query type
        query_type = 'tail' if 'monitor' in intent or 'stream' in intent else 'query'

        return {
            'type': query_type,
            'services': list(services),
            'levels': list(levels) if levels else [],  # Empty list = no level filter = all logs
            'keywords': list(keywords),
            'time_range': time_range
        }

    def _parse_time_range(self, text: str) -> Dict[str, str]:
        """Extract time range from text"""
        now = datetime.now()
        text_lower = text.lower()

        # Pattern matching for time expressions
        patterns = {
            'last hour': timedelta(hours=1),
            'past hour': timedelta(hours=1),
            'last day': timedelta(days=1),
            'past day': timedelta(days=1),
            'last week': timedelta(days=7),
            'recent': timedelta(minutes=15),
        }

        for pattern, delta in patterns.items():
            if pattern in text_lower:
                return {
                    'start': (now - delta).isoformat() + 'Z',
                    'end': now.isoformat() + 'Z'
                }

        # Check for "X ago" pattern (e.g., "one hour ago", "5 minutes ago")
        match = re.search(r'(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(second|minute|hour|day|week)s?\s+ago', text_lower)
        if match:
            amount_str = match.group(1)
            unit = match.group(2)

            # Convert word numbers to digits
            word_to_num = {
                'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
                'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10
            }
            amount = word_to_num.get(amount_str, int(amount_str) if amount_str.isdigit() else 1)

            if 'second' in unit:
                delta = timedelta(seconds=amount)
            elif 'minute' in unit:
                delta = timedelta(minutes=amount)
            elif 'hour' in unit:
                delta = timedelta(hours=amount)
            elif 'day' in unit:
                delta = timedelta(days=amount)
            elif 'week' in unit:
                delta = timedelta(weeks=amount)
            else:
                delta = timedelta(hours=1)

            return {
                'start': (now - delta).isoformat() + 'Z',
                'end': now.isoformat() + 'Z'
            }

        # Check for relative time with "last/past"
        match = re.search(r'(last|past)\s+(\d+)\s+(minute|hour|day|week)s?', text_lower)
        if match:
            amount = int(match.group(2))
            unit = match.group(3)
            if 'minute' in unit:
                delta = timedelta(minutes=amount)
            elif 'hour' in unit:
                delta = timedelta(hours=amount)
            elif 'day' in unit:
                delta = timedelta(days=amount)
            elif 'week' in unit:
                delta = timedelta(weeks=amount)
            else:
                delta = timedelta(hours=1)

            return {
                'start': (now - delta).isoformat() + 'Z',
                'end': now.isoformat() + 'Z'
            }

        # Default to last hour
        return {
            'start': (now - timedelta(hours=1)).isoformat() + 'Z',
            'end': now.isoformat() + 'Z'
        }

class LogsQLBuilder:
    """Build LogsQL queries from parsed intents"""

    def build(self, intent: Dict[str, Any]) -> str:
        """Build LogsQL query from intent"""
        conditions = []

        # Add time filter first for optimization
        if intent.get('time_range'):
            start = intent['time_range'].get('start')
            end = intent['time_range'].get('end')
            if start and end:
                conditions.append(f"_time:[{start}, {end}]")

        # Add service filters
        if intent.get('services'):
            service_conditions = [f"service:{s}" for s in intent['services']]
            if len(service_conditions) > 1:
                conditions.append(f"({' OR '.join(service_conditions)})")
            else:
                conditions.append(service_conditions[0])

        # Add severity filters
        if intent.get('levels'):
            level_conditions = [f"level:{l}" for l in intent['levels']]
            if len(level_conditions) > 1:
                conditions.append(f"({' OR '.join(level_conditions)})")
            else:
                conditions.append(level_conditions[0])

        # Add keyword search
        if intent.get('keywords'):
            keyword_conditions = [f'_msg:"{k}"' for k in intent['keywords']]
            if len(keyword_conditions) > 1:
                conditions.append(f"({' OR '.join(keyword_conditions)})")
            else:
                conditions.append(keyword_conditions[0])

        return ' AND '.join(conditions) if conditions else ""

class CroitLogSearchClient:
    """Client for Croit log searching via WebSocket"""

    def __init__(self, host: str, port: int = 8080, api_token: Optional[str] = None, use_ssl: bool = False):
        self.host = host
        self.port = port
        self.api_token = api_token
        self.use_ssl = use_ssl

        # Build URLs with correct protocol
        ws_protocol = "wss" if use_ssl else "ws"
        http_protocol = "https" if use_ssl else "http"
        self.ws_url = f"{ws_protocol}://{host}:{port}/api/logs"
        self.http_url = f"{http_protocol}://{host}:{port}"

        self.parser = LogSearchIntentParser()
        self.builder = LogsQLBuilder()

        # Cache for results
        self.cache = {}
        self.cache_ttl = 300  # 5 minutes

    async def search_logs(self, search_query: str, limit: int = 1000) -> Dict[str, Any]:
        """Search logs using natural language query"""

        # Check cache
        cache_key = hashlib.md5(f"{search_query}{limit}".encode()).hexdigest()
        if cache_key in self.cache:
            cached = self.cache[cache_key]
            if (datetime.now() - cached['timestamp']).seconds < self.cache_ttl:
                return cached['data']

        # Parse intent
        intent = self.parser.parse(search_query)

        # Build LogsQL query
        query = self.builder.build(intent)

        # Prepare request
        request = {
            "type": intent.get('type', 'query'),
            "query": {
                "where": query,
                "limit": limit
            }
        }

        if intent.get('time_range'):
            request["start"] = intent['time_range'].get('start')
            request["end"] = intent['time_range'].get('end')

        # Execute query
        try:
            logs = await self._execute_websocket_query(request)
        except Exception as e:
            logger.error(f"WebSocket failed: {e}, falling back to HTTP")
            logs = await self._execute_http_query(request)

        # Analyze results
        patterns = self._analyze_patterns(logs) if logs else []
        insights = self._generate_insights(logs, patterns)

        result = {
            "query": query,
            "intent": intent,
            "total_count": len(logs) if logs else 0,
            "results": logs[:100] if logs else [],  # Limit for response size
            "patterns": patterns[:10],  # Limit patterns
            "insights": insights
        }

        # Cache result
        self.cache[cache_key] = {
            'timestamp': datetime.now(),
            'data': result
        }

        return result

    async def _execute_websocket_query(self, request: Dict) -> List[Dict]:
        """Execute query via WebSocket"""
        logs = []
        headers = {}

        if self.api_token:
            headers['Authorization'] = f'Bearer {self.api_token}'

        try:
            async with websockets.connect(
                self.ws_url,
                extra_headers=headers if headers else None,
                ping_interval=20
            ) as websocket:
                # Send query
                await websocket.send(json.dumps(request))

                # Collect responses
                start = datetime.now()
                while (datetime.now() - start).seconds < 30:
                    try:
                        response = await asyncio.wait_for(
                            websocket.recv(),
                            timeout=5.0
                        )
                        if response:
                            try:
                                log_entry = json.loads(response)
                                logs.append(log_entry)
                            except json.JSONDecodeError:
                                logger.warning(f"Non-JSON response: {response[:100]}")
                    except asyncio.TimeoutError:
                        break
                    except websockets.exceptions.ConnectionClosed:
                        break

        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            raise

        return logs

    async def _execute_http_query(self, request: Dict) -> List[Dict]:
        """Fallback HTTP query execution"""
        logs = []

        headers = {'Content-Type': 'application/json'}
        if self.api_token:
            headers['Authorization'] = f'Bearer {self.api_token}'

        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.http_url}/logs/export"
                params = {
                    'format': 'json',
                    'query': json.dumps(request)
                }

                async with session.get(url, params=params, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        logs = data.get('logs', [])
                    else:
                        logger.error(f"HTTP query failed with status {response.status}")

        except Exception as e:
            logger.error(f"HTTP query failed: {e}")

        return logs

    def _analyze_patterns(self, logs: List[Dict]) -> List[Dict]:
        """Analyze log patterns"""
        patterns = []

        if not logs:
            return patterns

        # Error clustering
        error_clusters = defaultdict(list)
        for log in logs:
            if log.get('level') in ['ERROR', 'FATAL']:
                msg = log.get('message', '')
                # Normalize for clustering
                normalized = re.sub(r'\b\d+\b', 'N', msg)
                normalized = re.sub(r'\b[0-9a-f]{8,}\b', 'HEX', normalized)[:100]
                error_clusters[normalized].append(log)

        # Create patterns
        for cluster_key, cluster_logs in error_clusters.items():
            if len(cluster_logs) >= 2:
                patterns.append({
                    'type': 'repeated_error',
                    'pattern': cluster_key[:50],
                    'count': len(cluster_logs),
                    'hosts': list(set(l.get('host', '') for l in cluster_logs)),
                    'services': list(set(l.get('service', '') for l in cluster_logs))
                })

        # Detect bursts
        time_buckets = defaultdict(list)
        for log in logs:
            if 'timestamp' in log:
                try:
                    ts = datetime.fromisoformat(log['timestamp'].replace('Z', '+00:00'))
                    bucket = ts.strftime('%Y-%m-%d %H:%M')
                    time_buckets[bucket].append(log)
                except:
                    continue

        for bucket, bucket_logs in time_buckets.items():
            if len(bucket_logs) > 50:
                patterns.append({
                    'type': 'burst',
                    'time': bucket,
                    'count': len(bucket_logs),
                    'error_count': sum(1 for l in bucket_logs if l.get('level') in ['ERROR', 'FATAL'])
                })

        return patterns

    def _generate_insights(self, logs: List[Dict], patterns: List[Dict]) -> Dict:
        """Generate insights from logs and patterns"""
        insights = {
            'summary': '',
            'severity': 'normal',
            'recommendations': []
        }

        if not logs:
            insights['summary'] = "No logs found matching the search criteria"
            return insights

        # Calculate metrics
        total = len(logs)
        errors = sum(1 for l in logs if l.get('level') == 'ERROR')
        fatals = sum(1 for l in logs if l.get('level') == 'FATAL')

        # Determine severity
        if fatals > 0:
            insights['severity'] = 'critical'
            insights['summary'] = f"CRITICAL: {fatals} fatal errors found"
        elif errors > 20:
            insights['severity'] = 'high'
            insights['summary'] = f"HIGH: {errors} errors detected"
        elif errors > 5:
            insights['severity'] = 'medium'
            insights['summary'] = f"MEDIUM: {errors} errors found"
        else:
            insights['summary'] = f"Analyzed {total} logs"

        # Generate recommendations
        for pattern in patterns[:3]:
            if pattern['type'] == 'repeated_error':
                insights['recommendations'].append(
                    f"Investigate repeated error on {len(pattern['hosts'])} hosts"
                )
            elif pattern['type'] == 'burst':
                insights['recommendations'].append(
                    f"Check event at {pattern['time']} ({pattern['count']} logs)"
                )

        return insights

async def _execute_croit_websocket(host: str, port: int, api_token: str, use_ssl: bool, query: Dict) -> List[Dict]:
    """Execute direct Croit WebSocket query with VictoriaLogs JSON format"""
    import json
    import asyncio
    import websockets

    # Build WebSocket URL
    ws_protocol = "wss" if use_ssl else "ws"
    ws_url = f"{ws_protocol}://{host}:{port}/api/logs"

    logs = []
    control_messages = []

    try:
        async with websockets.connect(
            ws_url,
            ping_interval=20
        ) as websocket:
            # CRITICAL: Send auth token as binary data (first message)
            if api_token:
                await websocket.send(api_token.encode('utf-8'))

            # Send Croit JSON query
            await websocket.send(json.dumps(query))

            # Collect log entries
            start_time = asyncio.get_event_loop().time()
            while (asyncio.get_event_loop().time() - start_time) < 30:  # 30 second timeout
                try:
                    response = await asyncio.wait_for(
                        websocket.recv(),
                        timeout=5.0
                    )
                    if response:
                        # Handle control messages
                        if response == "clear":
                            control_messages.append({"type": "clear", "message": "Log display cleared"})
                        elif response == "empty":
                            control_messages.append({"type": "empty", "message": "No logs found for current query"})
                        elif response == "too_wide":
                            control_messages.append({"type": "too_wide", "message": "Query too broad (>1M logs), please add more filters"})
                        elif response.startswith("hits:"):
                            try:
                                hits_data = json.loads(response[5:].strip()) if response[5:].strip() != "null" else None
                                control_messages.append({"type": "hits", "data": hits_data})
                            except json.JSONDecodeError:
                                logger.warning(f"Failed to parse hits data: {response}")
                        elif response.startswith("error:"):
                            error_msg = response[6:].strip()
                            control_messages.append({"type": "error", "message": error_msg})
                            logger.error(f"VictoriaLogs error: {error_msg}")
                        else:
                            # Regular log entry
                            try:
                                log_entry = json.loads(response)
                                logs.append(log_entry)
                            except json.JSONDecodeError:
                                logger.warning(f"Non-JSON response: {response[:100]}")
                except asyncio.TimeoutError:
                    break
                except websockets.exceptions.ConnectionClosed:
                    break

    except Exception as e:
        logger.error(f"WebSocket query failed: {e}")
        raise

    return {
        "logs": logs,
        "control_messages": control_messages
    }

# Integration functions for MCP Server
async def handle_log_search(arguments: Dict, host: str, port: int = 8080) -> Dict[str, Any]:
    """Handle direct VictoriaLogs JSON query"""
    import time
    from datetime import datetime, timedelta

    where_clause = arguments.get('where')
    search_text = arguments.get('_search', '')
    limit = arguments.get('limit', 1000)
    after = arguments.get('after', 0)
    hours_back = arguments.get('hours_back', 1)
    start_timestamp = arguments.get('start_timestamp')
    end_timestamp = arguments.get('end_timestamp')
    api_token = arguments.get('api_token')
    use_ssl = arguments.get('use_ssl', False)

    if not where_clause:
        return {
            "code": 400,
            "error": "VictoriaLogs 'where' clause is required"
        }

    try:
        # Calculate time range
        if start_timestamp and end_timestamp:
            start = start_timestamp
            end = end_timestamp
        else:
            end = int(time.time())
            start = end - (hours_back * 3600)

        # Build Croit WebSocket query
        croit_query = {
            "type": "query",
            "start": start,
            "end": end,
            "query": {
                "where": where_clause,
                "_search": search_text,
                "after": after,
                "limit": limit
            }
        }

        # Execute query via WebSocket
        response = await _execute_croit_websocket(host, port, api_token, use_ssl, croit_query)
        logs = response["logs"]
        control_messages = response["control_messages"]

        return {
            "code": 200,
            "result": {
                "logs": logs,
                "total_count": len(logs),
                "control_messages": control_messages,
                "time_range": {
                    "start_timestamp": start,
                    "end_timestamp": end,
                    "hours_searched": hours_back
                }
            },
            "debug": {
                "croit_query": croit_query,
                "where_clause": where_clause,
                "time_range_human": f"{datetime.fromtimestamp(start)} to {datetime.fromtimestamp(end)}"
            }
        }

    except Exception as e:
        logger.error(f"Log search failed: {e}")
        return {
            "code": 500,
            "error": str(e),
            "debug": {
                "attempted_query": croit_query if 'croit_query' in locals() else None
            }
        }

async def handle_log_check(arguments: Dict, host: str, port: int = 8080) -> Dict[str, Any]:
    """
    Check log conditions immediately (snapshot) - suitable for LLMs
    Returns results immediately instead of monitoring for a duration
    """

    conditions = arguments.get('conditions', [])
    alert_threshold = arguments.get('threshold', 5)
    time_window = arguments.get('time_window', 300)  # Check last 5 minutes by default
    api_token = arguments.get('api_token')
    use_ssl = arguments.get('use_ssl', False)

    if not conditions:
        return {
            "code": 400,
            "error": "Conditions are required"
        }

    try:
        client = CroitLogSearchClient(host, port, api_token, use_ssl)
        alerts = []
        checks = []

        # Check each condition ONCE
        for condition in conditions:
            # Add time window to condition
            enhanced_condition = f"{condition} in the last {time_window} seconds"

            result = await client.search_logs(enhanced_condition, limit=100)

            check_result = {
                'condition': condition,
                'count': result['total_count'],
                'threshold': alert_threshold,
                'triggered': result['total_count'] >= alert_threshold,
                'severity': result['insights']['severity'] if result['total_count'] > 0 else 'none',
                'timestamp': datetime.now().isoformat()
            }

            checks.append(check_result)

            if check_result['triggered']:
                alerts.append({
                    'condition': condition,
                    'count': result['total_count'],
                    'severity': result['insights']['severity'],
                    'sample_logs': result['results'][:3] if result['results'] else []
                })

        return {
            "code": 200,
            "result": {
                "checks": checks,
                "alerts": alerts,
                "summary": f"{len(alerts)} of {len(conditions)} conditions triggered",
                "time_window": f"Last {time_window} seconds",
                "recommendation": "Run again later to check for changes" if alerts else "All clear"
            }
        }

    except Exception as e:
        logger.error(f"Log check failed: {e}")
        return {
            "code": 500,
            "error": str(e)
        }

# Keep for backwards compatibility but mark as deprecated
async def handle_log_monitor(arguments: Dict, host: str, port: int = 8080) -> Dict[str, Any]:
    """DEPRECATED: Use handle_log_check instead - this blocks for too long"""
    # Redirect to log_check with a warning
    logger.warning("handle_log_monitor is deprecated - using handle_log_check instead")
    return await handle_log_check(arguments, host, port)

# Tool definitions for MCP
LOG_SEARCH_TOOLS = [
    {
        "name": "croit_log_search",
        "description": """Search Croit/Ceph cluster logs using comprehensive VictoriaLogs JSON syntax.

AVAILABLE FILTER FIELDS:
• _SYSTEMD_UNIT: systemd service unit (string) - e.g. "ceph-mon", "ceph-osd@12"
• PRIORITY: log priority/severity (integer: 0=emerg, 1=alert, 2=crit, 3=err, 4=warning, 5=notice, 6=info, 7=debug)
• CROIT_SERVER_ID: specific Ceph node ID (string/integer) - e.g. "1", "2", "3"
• MESSAGE: log message content (string)
• _TRANSPORT: log transport method (string) - e.g. "kernel", "syslog", "journal"
• _HOSTNAME: server hostname (string) - e.g. "storage-node-01"
• _MACHINE_ID: unique machine identifier (string)
• SYSLOG_IDENTIFIER: service identifier (string) - e.g. "ceph-osd"
• THREAD: thread identifier (string) - e.g. "worker-1"
• _search: full-text search across all fields (string) - searches within message content

COMPARISON OPERATORS:

STRING OPERATORS:
• _eq: exact match {"field": {"_eq": "value"}}
• _contains: substring match {"field": {"_contains": "substring"}}
• _starts_with: prefix match {"MESSAGE": {"_starts_with": "ERROR:"}}
• _ends_with: suffix match {"MESSAGE": {"_ends_with": "failed"}}

NUMERIC OPERATORS:
• _eq: exact equal {"PRIORITY": {"_eq": 4}}
• _neq: not equal {"PRIORITY": {"_neq": 7}}
• _gt: greater than {"PRIORITY": {"_gt": 3}}
• _gte: greater than or equal {"PRIORITY": {"_gte": 4}}
• _lt: less than {"PRIORITY": {"_lt": 6}}
• _lte: less than or equal {"PRIORITY": {"_lte": 6}}

LIST/ARRAY OPERATORS:
• _in: value in list {"PRIORITY": {"_in": [0, 1, 2, 3]}}
• _nin: value not in list {"CROIT_SERVER_ID": {"_nin": ["1", "2"]}}

PATTERN OPERATORS:
• _regex: regular expression match {"MESSAGE": {"_regex": "OSD\\.[0-9]+"}}

EXISTENCE OPERATORS:
• _exists: field exists {"OPTIONAL_FIELD": {"_exists": true}}
• _missing: field missing {"OPTIONAL_FIELD": {"_missing": true}}

LOGICAL OPERATORS:
• _and: logical AND - all conditions must match
• _or: logical OR - at least one condition must match
• _not: negation - condition must NOT match

CEPH SERVICE MAPPING:
• OSD N: {"_SYSTEMD_UNIT": {"_contains": "ceph-osd@N"}}
• Monitor: {"_SYSTEMD_UNIT": {"_contains": "ceph-mon"}}
• Manager: {"_SYSTEMD_UNIT": {"_contains": "ceph-mgr"}}
• MDS: {"_SYSTEMD_UNIT": {"_contains": "ceph-mds"}}
• RGW: {"_SYSTEMD_UNIT": {"_contains": "ceph-radosgw"}}

TRANSPORT TYPES:
• kernel: Kernel-level logs (hardware, drivers, low-level system)
• syslog: Standard system logs
• journal: Systemd journal logs

COMPLEX QUERY EXAMPLES:

1. Monitor logs on server 1 (from your example):
{"where": {"_and": [
  {"_SYSTEMD_UNIT": {"_contains": "ceph-mon"}},
  {"PRIORITY": {"_lte": 6}},
  {"CROIT_SERVER_ID": {"_eq": "1"}}
]}}

2. Kernel logs on server 1:
{"where": {"_and": [
  {"_TRANSPORT": {"_eq": "kernel"}},
  {"PRIORITY": {"_lte": 6}},
  {"CROIT_SERVER_ID": {"_eq": "1"}}
]}}

3. Kernel logs with error search (note _search is outside where clause):
{
  "where": {"_and": [
    {"_TRANSPORT": {"_eq": "kernel"}},
    {"PRIORITY": {"_lte": 6}},
    {"CROIT_SERVER_ID": {"_eq": "1"}}
  ]},
  "_search": "error"
}

4. OSD 12 errors and warnings only:
{"where": {"_and": [
  {"_SYSTEMD_UNIT": {"_contains": "ceph-osd@12"}},
  {"PRIORITY": {"_lte": 4}}
]}}

5. Critical errors on specific server:
{"where": {"_and": [
  {"PRIORITY": {"_lte": 3}},
  {"CROIT_SERVER_ID": {"_eq": "1"}}
]}}

3. Multiple priority levels (errors + warnings):
{"where": {"PRIORITY": {"_in": [3, 4]}}}

4. Exclude specific servers from search:
{"where": {"_and": [
  {"_SYSTEMD_UNIT": {"_contains": "ceph-osd"}},
  {"CROIT_SERVER_ID": {"_not_in": ["1", "2", "3"]}}
]}}

5. Info and above (exclude debug):
{"where": {"PRIORITY": {"_ne": 7}}}

6. Monitor OR manager logs with text search:
{"where": {"_and": [
  {"_or": [
    {"_SYSTEMD_UNIT": {"_contains": "ceph-mon"}},
    {"_SYSTEMD_UNIT": {"_contains": "ceph-mgr"}}
  ]},
  {"_search": "election"}
]}}

7. Range filtering - warnings to critical:
{"where": {"_and": [
  {"PRIORITY": {"_gte": 2}},
  {"PRIORITY": {"_lte": 4}}
]}}

8. Error messages with specific prefix:
{"where": {"_and": [
  {"PRIORITY": {"_lt": 5}},
  {"MESSAGE": {"_starts_with": "failed to"}}
]}}

9. Complex filtering with message content:
{"where": {"_and": [
  {"_SYSTEMD_UNIT": {"_contains": "ceph-osd"}},
  {"PRIORITY": {"_lte": 6}},
  {"_or": [
    {"MESSAGE": {"_contains": "slow"}},
    {"MESSAGE": {"_contains": "timeout"}}
  ]},
  {"_not": {"MESSAGE": {"_contains": "heartbeat"}}}
]}}

10. Multiple OSDs with priority filtering:
{"where": {"_and": [
  {"_or": [
    {"_SYSTEMD_UNIT": {"_contains": "ceph-osd@12"}},
    {"_SYSTEMD_UNIT": {"_contains": "ceph-osd@13"}},
    {"_SYSTEMD_UNIT": {"_contains": "ceph-osd@14"}}
  ]},
  {"PRIORITY": {"_in": [0, 1, 2, 3, 4]}}
]}}

PRIORITY LEVELS (syslog standard):
• 0: Emergency (system unusable)
• 1: Alert (immediate action required)
• 2: Critical (critical conditions)
• 3: Error (error conditions)
• 4: Warning (warning conditions)
• 5: Notice (normal but significant)
• 6: Info (informational messages)
• 7: Debug (debug-level messages)

NESTED LOGIC SUPPORT:
Use unlimited nesting with _and/_or/_not for complex conditions.

TIME CONTROL:
• hours_back: number of hours to search back (default: 1)
• start_timestamp/end_timestamp: explicit Unix timestamps

OUTPUT: Logs + debug info showing exact query sent to VictoriaLogs""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "where": {
                    "type": "object",
                    "description": "VictoriaLogs JSON where clause (see examples above)"
                },
                "_search": {
                    "type": "string",
                    "default": "",
                    "description": "Full-text search string (optional) - searches within message content"
                },
                "limit": {
                    "type": "integer",
                    "default": 1000,
                    "description": "Maximum number of logs to return"
                },
                "after": {
                    "type": "integer",
                    "default": 0,
                    "description": "Offset for pagination (number of logs to skip)"
                },
                "hours_back": {
                    "type": "integer",
                    "default": 1,
                    "description": "Hours to search back from now (ignored if timestamps provided)"
                },
                "start_timestamp": {
                    "type": "integer",
                    "description": "Unix timestamp start (optional)"
                },
                "end_timestamp": {
                    "type": "integer",
                    "description": "Unix timestamp end (optional)"
                }
            },
            "required": ["where"]
        }
    },
    {
        "name": "croit_log_check",
        "description": """Check specific log conditions instantly (non-blocking snapshot).

USE CASES:
• Quick health checks: "Are there any OSD failures right now?"
• Validation after operations: "Check for errors after pool creation"
• Threshold monitoring: "Alert if more than 5 slow requests"

CONDITIONS FORMAT:
• Natural language conditions to check
• Each condition is evaluated separately
• Returns matches for each condition

EXAMPLES:
• conditions: ["OSD failures", "slow requests over 5s", "authentication errors"]
• conditions: ["pool full warnings", "network timeouts"]
• conditions: ["any ERROR level logs"]

PARAMETERS:
• threshold: How many logs must match to trigger alert (default: 5)
• time_window: Check logs from last N seconds (default: 300 = 5 minutes)

RETURNS:
• List of triggered conditions with matching log counts
• Sample of matching logs for each condition
• Overall status (triggered/clear)""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "conditions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of conditions to check in natural language"
                },
                "threshold": {
                    "type": "integer",
                    "default": 5,
                    "description": "Number of matching logs to trigger alert (default: 5)"
                },
                "time_window": {
                    "type": "integer",
                    "default": 300,
                    "description": "Time window in seconds to check (default: 300 = 5 min)"
                },
                "api_token": {
                    "type": "string",
                    "description": "Optional API token for authentication"
                }
            },
            "required": ["conditions"]
        }
    }
]