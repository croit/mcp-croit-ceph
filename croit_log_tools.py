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

        # Parse time range
        time_range = self._parse_time_range(intent)

        # Determine query type
        query_type = 'tail' if 'monitor' in intent or 'stream' in intent else 'query'

        return {
            'type': query_type,
            'services': list(services),
            'levels': list(levels) if levels else ['ERROR', 'WARN'],
            'keywords': list(keywords),
            'time_range': time_range
        }

    def _parse_time_range(self, text: str) -> Dict[str, str]:
        """Extract time range from text"""
        now = datetime.now()

        # Pattern matching for time expressions
        patterns = {
            'last hour': timedelta(hours=1),
            'last day': timedelta(days=1),
            'last week': timedelta(days=7),
            'recent': timedelta(minutes=15),
        }

        for pattern, delta in patterns.items():
            if pattern in text:
                return {
                    'start': (now - delta).isoformat() + 'Z',
                    'end': now.isoformat() + 'Z'
                }

        # Check for relative time
        match = re.search(r'last (\d+) (minute|hour|day)s?', text)
        if match:
            amount = int(match.group(1))
            unit = match.group(2)
            if 'minute' in unit:
                delta = timedelta(minutes=amount)
            elif 'hour' in unit:
                delta = timedelta(hours=amount)
            else:
                delta = timedelta(days=amount)

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

    def __init__(self, host: str, port: int = 8080, api_token: Optional[str] = None):
        self.host = host
        self.port = port
        self.api_token = api_token
        self.ws_url = f"ws://{host}:{port}/api/logs"
        self.http_url = f"http://{host}:{port}"
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

# Integration functions for MCP Server
async def handle_log_search(arguments: Dict, host: str, port: int = 8080) -> Dict[str, Any]:
    """Handle log search tool call"""

    search_query = arguments.get('search', '')
    limit = arguments.get('limit', 1000)
    api_token = arguments.get('api_token')

    if not search_query:
        return {
            "code": 400,
            "error": "Search query is required"
        }

    try:
        client = CroitLogSearchClient(host, port, api_token)
        result = await client.search_logs(search_query, limit)

        return {
            "code": 200,
            "result": result
        }

    except Exception as e:
        logger.error(f"Log search failed: {e}")
        return {
            "code": 500,
            "error": str(e)
        }

async def handle_log_monitor(arguments: Dict, host: str, port: int = 8080) -> Dict[str, Any]:
    """Handle log monitoring tool call"""

    conditions = arguments.get('conditions', [])
    duration = arguments.get('duration', 60)
    alert_threshold = arguments.get('threshold', 5)
    api_token = arguments.get('api_token')

    if not conditions:
        return {
            "code": 400,
            "error": "Monitoring conditions are required"
        }

    try:
        client = CroitLogSearchClient(host, port, api_token)
        alerts = []
        start_time = datetime.now()

        while (datetime.now() - start_time).seconds < duration:
            for condition in conditions:
                result = await client.search_logs(condition, limit=100)

                if result['total_count'] >= alert_threshold:
                    alerts.append({
                        'condition': condition,
                        'count': result['total_count'],
                        'timestamp': datetime.now().isoformat(),
                        'severity': result['insights']['severity']
                    })

            await asyncio.sleep(5)  # Check every 5 seconds

        return {
            "code": 200,
            "result": {
                "monitoring_duration": duration,
                "conditions": conditions,
                "alerts": alerts
            }
        }

    except Exception as e:
        logger.error(f"Log monitoring failed: {e}")
        return {
            "code": 500,
            "error": str(e)
        }

# Tool definitions for MCP
LOG_SEARCH_TOOLS = [
    {
        "name": "croit_log_search",
        "description": "Search Croit logs using natural language queries. Examples: 'Find OSD failures in the last hour', 'Show slow requests', 'What errors occurred today'",
        "inputSchema": {
            "type": "object",
            "properties": {
                "search": {
                    "type": "string",
                    "description": "Natural language search query"
                },
                "limit": {
                    "type": "integer",
                    "default": 1000,
                    "description": "Maximum number of logs to return"
                },
                "api_token": {
                    "type": "string",
                    "description": "Optional API token for authentication"
                }
            },
            "required": ["search"]
        }
    },
    {
        "name": "croit_log_monitor",
        "description": "Monitor Croit logs for specific conditions in real-time",
        "inputSchema": {
            "type": "object",
            "properties": {
                "conditions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of conditions to monitor (natural language)"
                },
                "duration": {
                    "type": "integer",
                    "default": 60,
                    "description": "Monitoring duration in seconds"
                },
                "threshold": {
                    "type": "integer",
                    "default": 5,
                    "description": "Alert threshold (number of matching logs)"
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