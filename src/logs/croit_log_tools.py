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
from collections import defaultdict, Counter
import aiohttp
import zipfile
import io

# Import utility functions
from src.utils.helpers import calculate_time_range

# Import constants
from src.config.constants import (
    DEFAULT_LOG_LIMIT,
    LOG_ANALYSIS_SAMPLE_SIZE,
    LOG_MEDIUM_SAMPLE_SIZE,
    DEFAULT_HTTP_PORT,
)

logger = logging.getLogger(__name__)


class LogSearchIntentParser:
    """Parse natural language into structured search intents"""

    PATTERNS = {
        "osd_issues": {
            "regex": r"(osd|OSD|object.?storage).*?(fail|down|crash|slow|error|flap|timeout)",
            "services": ["ceph-osd", "ceph-mon"],
            "levels": ["ERROR", "WARN", "FATAL"],
            "keywords": ["OSD", "failed", "down", "crashed", "flapping"],
        },
        "slow_requests": {
            "regex": r"(slow|blocked|stuck|delayed)\s+(request|operation|op|query|io)",
            "services": ["ceph-osd", "ceph-mon", "ceph-mds"],
            "levels": ["WARN", "ERROR"],
            "keywords": ["slow request", "blocked", "timeout", "stuck"],
        },
        "auth_failures": {
            "regex": r"(auth|authentication|login|permission).*?(fail|denied|error)",
            "services": ["ceph-mon", "ceph-mgr"],
            "levels": ["ERROR", "WARN"],
            "keywords": ["authentication", "failed", "denied", "unauthorized"],
        },
        "network_problems": {
            "regex": r"(network|connection|timeout|unreachable|heartbeat|msgr)",
            "services": ["ceph-mon", "ceph-osd", "ceph-mds", "ceph-mgr"],
            "levels": ["ERROR", "WARN"],
            "keywords": [
                "connection",
                "timeout",
                "network",
                "unreachable",
                "heartbeat",
            ],
        },
        "pool_issues": {
            "regex": r"pool.*?(full|create|delete|error)",
            "services": ["ceph-mon", "ceph-mgr"],
            "levels": ["ERROR", "WARN"],
            "keywords": ["pool", "full", "quota", "space"],
        },
    }

    def parse(self, search_intent: str) -> Dict[str, Any]:
        """Parse natural language search intent"""
        intent = search_intent.lower()

        # Detect Ceph service references and translate them
        ceph_services = CephServiceTranslator.detect_ceph_services_in_text(
            search_intent
        )
        translated_services = []
        for service in ceph_services:
            translated = CephServiceTranslator.translate_service_name(service)
            translated_services.append(translated)
            # Replace in intent for better pattern detection
            intent = intent.replace(service.lower(), translated.lower())

        # Detect patterns
        detected_patterns = []
        for pattern_name, pattern_def in self.PATTERNS.items():
            if re.search(pattern_def["regex"], intent, re.IGNORECASE):
                detected_patterns.append(pattern_name)

        # Extract components
        services = set()
        levels = set()
        keywords = set()

        # Add translated Ceph services
        services.update(translated_services)

        for pattern_name in detected_patterns:
            pattern = self.PATTERNS[pattern_name]
            services.update(pattern["services"])
            levels.update(pattern["levels"])
            keywords.update(pattern["keywords"])

        # Enhanced level detection with kernel-specific handling
        intent_lower = intent.lower()

        # Explicit level requests
        if (
            "all level" in intent_lower
            or "all log" in intent_lower
            or "everything" in intent_lower
        ):
            levels = set()  # No level filter
        elif "critical" in intent_lower or "emergency" in intent_lower:
            levels.update(["EMERGENCY", "ALERT", "CRITICAL"])
        elif "error" in intent_lower and "no error" not in intent_lower:
            levels.update(["ERROR", "CRITICAL", "ALERT", "EMERGENCY"])
        elif "warning" in intent_lower or "warn" in intent_lower:
            levels.update(["WARNING", "ERROR", "CRITICAL", "ALERT", "EMERGENCY"])
        elif "info" in intent_lower and "info" not in " ".join(keywords).lower():
            levels.update(
                ["INFO", "WARNING", "ERROR", "CRITICAL", "ALERT", "EMERGENCY"]
            )
        elif "debug" in intent_lower:
            levels.update(
                ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "ALERT", "EMERGENCY"]
            )
        elif "trace" in intent_lower:
            levels = set()  # All levels for trace

        # Kernel-specific optimizations
        kernel_mentioned = any(
            word in intent_lower for word in ["kernel", "hardware", "driver", "system"]
        )
        if kernel_mentioned:
            # For kernel logs, focus on more critical levels by default
            if not levels and not any(
                word in intent_lower
                for word in ["all", "everything", "debug", "trace", "info"]
            ):
                levels.update(["WARNING", "ERROR", "CRITICAL", "ALERT", "EMERGENCY"])

        # Smart defaults based on context
        problem_indicators = [
            "error",
            "fail",
            "problem",
            "issue",
            "crash",
            "wrong",
            "slow",
            "timeout",
            "stuck",
        ]
        if not levels and not any(
            word in intent_lower for word in problem_indicators + ["all", "everything"]
        ):
            # No explicit level and no problem indicators - get reasonable subset
            if kernel_mentioned:
                levels.update(
                    ["NOTICE", "WARNING", "ERROR", "CRITICAL", "ALERT", "EMERGENCY"]
                )
            else:
                levels = set()  # For service logs, get all levels

        # Performance queries often need broader scope
        performance_indicators = [
            "performance",
            "slow",
            "fast",
            "latency",
            "throughput",
            "bandwidth",
        ]
        if any(word in intent_lower for word in performance_indicators):
            if not levels or levels == {"ERROR", "WARNING"}:
                levels.update(
                    ["INFO", "NOTICE", "WARNING", "ERROR"]
                )  # Include info for performance data

        # Parse time range
        time_range = self._parse_time_range(intent)

        # Determine query type
        query_type = "tail" if "monitor" in intent or "stream" in intent else "query"

        return {
            "type": query_type,
            "services": list(services),
            "levels": (
                list(levels) if levels else []
            ),  # Empty list = no level filter = all logs
            "keywords": list(keywords),
            "time_range": time_range,
        }

    def _parse_time_range(self, text: str) -> Dict[str, str]:
        """Extract time range from text"""
        now = datetime.now()
        text_lower = text.lower()

        # Pattern matching for time expressions
        patterns = {
            "last hour": timedelta(hours=1),
            "past hour": timedelta(hours=1),
            "last day": timedelta(days=1),
            "past day": timedelta(days=1),
            "last week": timedelta(days=7),
            "recent": timedelta(minutes=15),
        }

        for pattern, delta in patterns.items():
            if pattern in text_lower:
                return {
                    "start": (now - delta).isoformat() + "Z",
                    "end": now.isoformat() + "Z",
                }

        # Check for "X ago" pattern (e.g., "one hour ago", "5 minutes ago")
        match = re.search(
            r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(second|minute|hour|day|week)s?\s+ago",
            text_lower,
        )
        if match:
            amount_str = match.group(1)
            unit = match.group(2)

            # Convert word numbers to digits
            word_to_num = {
                "one": 1,
                "two": 2,
                "three": 3,
                "four": 4,
                "five": 5,
                "six": 6,
                "seven": 7,
                "eight": 8,
                "nine": 9,
                "ten": 10,
            }
            amount = word_to_num.get(
                amount_str, int(amount_str) if amount_str.isdigit() else 1
            )

            if "second" in unit:
                delta = timedelta(seconds=amount)
            elif "minute" in unit:
                delta = timedelta(minutes=amount)
            elif "hour" in unit:
                delta = timedelta(hours=amount)
            elif "day" in unit:
                delta = timedelta(days=amount)
            elif "week" in unit:
                delta = timedelta(weeks=amount)
            else:
                delta = timedelta(hours=1)

            return {
                "start": (now - delta).isoformat() + "Z",
                "end": now.isoformat() + "Z",
            }

        # Check for relative time with "last/past"
        match = re.search(r"(last|past)\s+(\d+)\s+(minute|hour|day|week)s?", text_lower)
        if match:
            amount = int(match.group(2))
            unit = match.group(3)
            if "minute" in unit:
                delta = timedelta(minutes=amount)
            elif "hour" in unit:
                delta = timedelta(hours=amount)
            elif "day" in unit:
                delta = timedelta(days=amount)
            elif "week" in unit:
                delta = timedelta(weeks=amount)
            else:
                delta = timedelta(hours=1)

            return {
                "start": (now - delta).isoformat() + "Z",
                "end": now.isoformat() + "Z",
            }

        # Default to last hour
        return {
            "start": (now - timedelta(hours=1)).isoformat() + "Z",
            "end": now.isoformat() + "Z",
        }


class LogsQLBuilder:
    """Build LogsQL queries from parsed intents"""

    def build(self, intent: Dict[str, Any]) -> str:
        """Build LogsQL query from intent"""
        conditions = []

        # Add time filter first for optimization
        if intent.get("time_range"):
            start = intent["time_range"].get("start")
            end = intent["time_range"].get("end")
            if start and end:
                conditions.append(f"_time:[{start}, {end}]")

        # Add service filters
        if intent.get("services"):
            service_conditions = [f"service:{s}" for s in intent["services"]]
            if len(service_conditions) > 1:
                conditions.append(f"({' OR '.join(service_conditions)})")
            else:
                conditions.append(service_conditions[0])

        # Add severity filters
        if intent.get("levels"):
            level_conditions = [f"level:{l}" for l in intent["levels"]]
            if len(level_conditions) > 1:
                conditions.append(f"({' OR '.join(level_conditions)})")
            else:
                conditions.append(level_conditions[0])

        # Add keyword search
        if intent.get("keywords"):
            keyword_conditions = [f'_msg:"{k}"' for k in intent["keywords"]]
            if len(keyword_conditions) > 1:
                conditions.append(f"({' OR '.join(keyword_conditions)})")
            else:
                conditions.append(keyword_conditions[0])

        return " AND ".join(conditions) if conditions else ""


class CroitLogSearchClient:
    """Client for Croit log searching via WebSocket"""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_HTTP_PORT,
        api_token: Optional[str] = None,
        use_ssl: bool = False,
    ):
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
        self.server_detector = ServerIDDetector(self)
        self.transport_analyzer = LogTransportAnalyzer(self)

        # Cache for results
        self.cache = {}
        self.cache_ttl = 300  # 5 minutes

    async def search_logs(self, search_query: str, limit: int = 1000) -> Dict[str, Any]:
        """Search logs using natural language query"""

        # Check cache
        cache_key = hashlib.md5(f"{search_query}{limit}".encode()).hexdigest()
        if cache_key in self.cache:
            cached = self.cache[cache_key]
            if (datetime.now() - cached["timestamp"]).seconds < self.cache_ttl:
                return cached["data"]

        # Parse intent
        intent = self.parser.parse(search_query)

        # Build LogsQL query
        query = self.builder.build(intent)

        # Prepare request
        request = {
            "type": intent.get("type", "query"),
            "query": {"where": query, "limit": limit},
        }

        if intent.get("time_range"):
            request["start"] = intent["time_range"].get("start")
            request["end"] = intent["time_range"].get("end")

        # Execute query
        try:
            logs = await self._execute_websocket_query(request)
            logger.debug(f"WebSocket query successful: {len(logs)} logs returned")
        except (
            websockets.exceptions.WebSocketException,
            ConnectionError,
            OSError,
            asyncio.TimeoutError,
        ) as e:
            # WebSocket connection issues - fall back to HTTP
            logger.warning(
                f"WebSocket failed ({type(e).__name__}), falling back to HTTP: {e}"
            )
            logs = await self._execute_http_query(request)
            logger.debug(f"HTTP fallback completed: {len(logs)} logs returned")

        # Analyze results with intelligent prioritization
        patterns = self._analyze_patterns(logs) if logs else []
        insights = self._generate_insights(logs, patterns)

        # Create log summary for better overview
        summary_engine = LogSummaryEngine()
        log_summary = summary_engine.summarize_logs(logs, max_details=20)

        # Intelligent truncation: prioritize critical events
        if logs and len(logs) > 100:
            # Get critical events with full log data
            critical_events = log_summary["critical_events"]
            critical_logs = [
                event["log"] for event in critical_events[:50]
            ]  # Top 50 critical

            # Fill remaining space with recent logs (avoiding duplicates)
            critical_log_ids = {id(log) for log in critical_logs}
            recent_logs = [log for log in logs[-50:] if id(log) not in critical_log_ids]

            intelligent_results = critical_logs + recent_logs
            intelligent_results = intelligent_results[:100]  # Final limit

            truncation_info = {
                "total_logs": len(logs),
                "shown_logs": len(intelligent_results),
                "critical_events_shown": len(critical_logs),
                "recent_logs_shown": len(recent_logs),
                "truncation_method": "intelligent_priority",
            }
        else:
            intelligent_results = logs[:100] if logs else []
            truncation_info = {
                "total_logs": len(logs) if logs else 0,
                "shown_logs": len(intelligent_results),
                "truncation_method": "simple_limit",
            }

        result = {
            "query": query,
            "intent": intent,
            "total_count": len(logs) if logs else 0,
            "results": intelligent_results,
            "patterns": patterns[:10],  # Limit patterns
            "insights": insights,
            "summary": log_summary,
            "truncation_info": truncation_info,
        }

        # Cache result
        self.cache[cache_key] = {"timestamp": datetime.now(), "data": result}

        return result

    # Log Level Shortcuts
    async def search_errors(
        self, query: str = "", hours_back: int = 24, limit: int = 100
    ) -> Dict[str, Any]:
        """Quick shortcut to search ERROR level logs"""
        search_query = f"error level priority ≤3 {query}".strip()
        return await self.search_logs_with_params(
            search_query=search_query,
            priority_max=3,
            hours_back=hours_back,
            limit=limit,
        )

    async def search_warnings(
        self, query: str = "", hours_back: int = 24, limit: int = 200
    ) -> Dict[str, Any]:
        """Quick shortcut to search WARNING level logs"""
        search_query = f"warning level priority ≤4 {query}".strip()
        return await self.search_logs_with_params(
            search_query=search_query,
            priority_max=4,
            hours_back=hours_back,
            limit=limit,
        )

    async def search_info(
        self, query: str = "", hours_back: int = 6, limit: int = 500
    ) -> Dict[str, Any]:
        """Quick shortcut to search INFO level logs"""
        search_query = f"info level priority ≤6 {query}".strip()
        return await self.search_logs_with_params(
            search_query=search_query,
            priority_max=6,
            hours_back=hours_back,
            limit=limit,
        )

    async def search_critical(
        self, query: str = "", hours_back: int = 48, limit: int = 50
    ) -> Dict[str, Any]:
        """Quick shortcut to search CRITICAL/EMERGENCY level logs"""
        search_query = f"critical emergency level priority ≤2 {query}".strip()
        return await self.search_logs_with_params(
            search_query=search_query,
            priority_max=2,
            hours_back=hours_back,
            limit=limit,
        )

    async def search_logs_with_params(
        self,
        search_query: str,
        priority_max: Optional[int] = None,
        hours_back: int = 24,
        limit: int = 1000,
        server_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Enhanced search with explicit parameters"""

        # Build query with specific parameters
        query_conditions = []

        # Priority filter
        if priority_max is not None:
            query_conditions.append({"PRIORITY": {"_lte": priority_max}})

        # Server filter
        if server_id:
            query_conditions.append({"CROIT_SERVERID": {"_eq": server_id}})

        # Time range
        start_time, end_time = calculate_time_range(hours_back)

        # Search text
        search_text = search_query.strip() if search_query.strip() else ""

        # Build the query
        base_query = {
            "type": "query",
            "start": start_time,
            "end": end_time,
            "query": {"where": {"_search": search_text}, "limit": limit},
        }

        # Add conditions if any
        if query_conditions:
            if len(query_conditions) == 1:
                # Merge single condition with _search
                base_query["query"]["where"] = {
                    "_and": [
                        query_conditions[0],
                        {"_search": search_text} if search_text else {},
                    ]
                }
                # Remove empty _search
                if not search_text:
                    base_query["query"]["where"]["_and"] = query_conditions
            else:
                # Multiple conditions
                all_conditions = query_conditions.copy()
                if search_text:
                    all_conditions.append({"_search": search_text})

                base_query["query"]["where"] = {"_and": all_conditions}

        # Execute query
        try:
            logs = await self._execute_http_query(base_query)
            logger.debug(f"Parameterized search completed: {len(logs)} logs returned")
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            # Network errors during HTTP query
            logger.error(f"Parameterized search failed ({type(e).__name__}): {e}")
            logs = []
        except json.JSONDecodeError as e:
            # Invalid JSON response
            logger.error(f"Invalid JSON in search response: {e}")
            logs = []

        # Calculate actual hours searched
        actual_hours_searched = (end_time - start_time) / 3600.0

        # Create summary
        summary_engine = LogSummaryEngine()
        log_summary = summary_engine.summarize_logs(logs, max_details=15)

        # Intelligent truncation
        if logs and len(logs) > limit // 2:  # Apply intelligent truncation
            critical_events = log_summary["critical_events"]
            critical_logs = [event["log"] for event in critical_events[: limit // 3]]
            recent_logs = logs[-(limit // 3) :] if len(logs) > limit // 3 else logs

            # Avoid duplicates
            critical_log_ids = {id(log) for log in critical_logs}
            recent_logs = [
                log for log in recent_logs if id(log) not in critical_log_ids
            ]

            final_logs = critical_logs + recent_logs
            final_logs = final_logs[: limit // 2]  # Final size control
        else:
            final_logs = logs

        return {
            "query_params": {
                "search_query": search_query,
                "priority_max": priority_max,
                "hours_back": hours_back,
                "server_id": server_id,
                "limit": limit,
            },
            "actual_query": base_query,
            "total_count": len(logs),
            "displayed_count": len(final_logs),
            "hours_searched": actual_hours_searched,
            "results": final_logs,
            "summary": log_summary,
            "execution_timestamp": datetime.now().isoformat(),
        }

    # Server Discovery
    async def discover_servers(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Discover available server IDs from recent logs"""
        return await self.server_detector.detect_servers(force_refresh)

    async def get_server_summary(self) -> str:
        """Get human-readable server summary"""
        server_info = await self.discover_servers()
        return self.server_detector.get_server_summary(server_info)

    # Transport Analysis
    async def analyze_log_transports(self, hours_back: int = 24) -> Dict[str, Any]:
        """Analyze available log transport types"""
        return await self.transport_analyzer.analyze_transports(hours_back)

    async def find_kernel_logs_debug(self, hours_back: int = 24) -> Dict[str, Any]:
        """Debug kernel log availability with multiple strategies"""
        return await self.transport_analyzer.find_kernel_logs(hours_back)

    # Response Size Optimization
    def optimize_response_size(
        self, data: Dict, max_log_entries: int = 50, max_message_length: int = 200
    ) -> Dict:
        """Optimize response size while preserving critical information"""

        optimized = data.copy()

        # Optimize log results
        if "results" in optimized and isinstance(optimized["results"], list):
            logs = optimized["results"]

            if len(logs) > max_log_entries:
                # Keep critical events + recent logs
                summary = optimized.get("summary", {})
                critical_events = summary.get("critical_events", [])

                # Get critical log entries
                critical_logs = []
                if critical_events:
                    critical_logs = [
                        event["log"]
                        for event in critical_events[: max_log_entries // 2]
                    ]

                # Get recent logs (avoiding duplicates)
                critical_ids = {id(log) for log in critical_logs}
                recent_logs = [
                    log
                    for log in logs[-(max_log_entries // 2) :]
                    if id(log) not in critical_ids
                ]

                optimized_logs = critical_logs + recent_logs
                optimized["results"] = optimized_logs[:max_log_entries]

                # Add optimization info
                optimized["optimization_applied"] = {
                    "original_count": len(logs),
                    "optimized_count": len(optimized["results"]),
                    "critical_events_kept": len(critical_logs),
                    "recent_logs_kept": len(recent_logs),
                    "method": "critical_events_plus_recent",
                }

        # Truncate long messages
        if "results" in optimized:
            for log in optimized["results"]:
                if "MESSAGE" in log and len(log["MESSAGE"]) > max_message_length:
                    log["MESSAGE"] = (
                        log["MESSAGE"][:max_message_length] + "...[truncated]"
                    )
                    log["_message_truncated"] = True

        # Optimize summary critical events
        if "summary" in optimized and "critical_events" in optimized["summary"]:
            events = optimized["summary"]["critical_events"]
            for event in events:
                if (
                    "message_preview" in event
                    and len(event["message_preview"]) > max_message_length
                ):
                    event["message_preview"] = (
                        event["message_preview"][:max_message_length] + "..."
                    )

        # Optimize patterns (keep only top patterns)
        if "patterns" in optimized and isinstance(optimized["patterns"], list):
            optimized["patterns"] = optimized["patterns"][:5]  # Top 5 patterns only

        return optimized

    async def search_optimized(
        self, search_query: str, limit: int = 1000, optimize_response: bool = True
    ) -> Dict[str, Any]:
        """Search with automatic response optimization"""

        result = await self.search_logs(search_query, limit)

        if optimize_response:
            # Apply size optimization
            result = self.optimize_response_size(
                result, max_log_entries=50, max_message_length=150
            )

        return result

    async def _execute_websocket_query(self, request: Dict) -> List[Dict]:
        """Execute query via WebSocket"""
        logs = []
        headers = {}

        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"

        try:
            async with websockets.connect(
                self.ws_url,
                extra_headers=headers if headers else None,
                ping_interval=20,
            ) as websocket:
                # Send query
                await websocket.send(json.dumps(request))

                # Collect responses
                start = datetime.now()
                while (datetime.now() - start).seconds < 30:
                    try:
                        response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
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

        except websockets.exceptions.WebSocketException as e:
            # WebSocket protocol errors
            logger.error(f"WebSocket protocol error: {e}")
            raise
        except (ConnectionError, OSError) as e:
            # Connection/network errors
            logger.error(f"WebSocket connection error: {e}")
            raise
        except json.JSONDecodeError as e:
            # Invalid JSON in WebSocket message
            logger.error(f"Invalid JSON in WebSocket message: {e}")
            raise

        return logs

    async def _execute_http_query(self, request: Dict) -> List[Dict]:
        """Fallback HTTP query execution"""
        logs = []

        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"

        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.http_url}/logs/export"
                params = {"format": "json", "query": json.dumps(request)}

                logger.debug(f"HTTP GET {url} with params: {params}")
                logger.debug(f"HTTP headers: {headers}")

                async with session.get(url, params=params, headers=headers) as response:
                    response_text = await response.text()
                    logger.debug(f"HTTP response status: {response.status}")
                    logger.debug(f"HTTP response headers: {dict(response.headers)}")
                    logger.debug(
                        f"HTTP response body (first 500 chars): {response_text[:500]}"
                    )

                    if response.status == 200:
                        try:
                            data = json.loads(response_text)
                            logs = data.get("logs", [])
                            logger.debug(
                                f"Successfully parsed JSON: {len(logs)} logs found"
                            )
                            if not logs:
                                logger.warning(
                                    f"HTTP response had no logs. Full response: {data}"
                                )
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse JSON response: {e}")
                            logger.error(f"Raw response: {response_text}")
                    else:
                        logger.error(f"HTTP query failed with status {response.status}")
                        logger.error(f"Error response body: {response_text}")

        except aiohttp.ClientError as e:
            # Network/connection errors
            logger.error(f"HTTP query failed - connection error: {e}")
        except asyncio.TimeoutError:
            # Request timeout
            logger.error(f"HTTP query failed - timeout")
        except json.JSONDecodeError as e:
            # Invalid JSON response
            logger.error(f"HTTP query failed - invalid JSON: {e}")

        return logs

    def _analyze_patterns(self, logs: List[Dict]) -> List[Dict]:
        """Analyze log patterns"""
        patterns = []

        if not logs:
            return patterns

        # Error clustering
        error_clusters = defaultdict(list)
        for log in logs:
            if log.get("level") in ["ERROR", "FATAL"]:
                msg = log.get("message", "")
                # Normalize for clustering
                normalized = re.sub(r"\b\d+\b", "N", msg)
                normalized = re.sub(r"\b[0-9a-f]{8,}\b", "HEX", normalized)[:100]
                error_clusters[normalized].append(log)

        # Create patterns
        for cluster_key, cluster_logs in error_clusters.items():
            if len(cluster_logs) >= 2:
                patterns.append(
                    {
                        "type": "repeated_error",
                        "pattern": cluster_key[:50],
                        "count": len(cluster_logs),
                        "hosts": list(set(l.get("host", "") for l in cluster_logs)),
                        "services": list(
                            set(l.get("service", "") for l in cluster_logs)
                        ),
                    }
                )

        # Detect bursts
        time_buckets = defaultdict(list)
        for log in logs:
            if "timestamp" in log:
                try:
                    ts = datetime.fromisoformat(log["timestamp"].replace("Z", "+00:00"))
                    bucket = ts.strftime("%Y-%m-%d %H:%M")
                    time_buckets[bucket].append(log)
                except (ValueError, AttributeError) as e:
                    # Invalid timestamp format, skip this log entry
                    logger.debug(f"Invalid timestamp in log entry: {e}")
                    continue

        for bucket, bucket_logs in time_buckets.items():
            if len(bucket_logs) > 50:
                patterns.append(
                    {
                        "type": "burst",
                        "time": bucket,
                        "count": len(bucket_logs),
                        "error_count": sum(
                            1
                            for l in bucket_logs
                            if l.get("level") in ["ERROR", "FATAL"]
                        ),
                    }
                )

        return patterns

    def _generate_insights(self, logs: List[Dict], patterns: List[Dict]) -> Dict:
        """Generate insights from logs and patterns"""
        insights = {"summary": "", "severity": "normal", "recommendations": []}

        if not logs:
            insights["summary"] = "No logs found matching the search criteria"
            return insights

        # Calculate metrics
        total = len(logs)
        errors = sum(1 for l in logs if l.get("level") == "ERROR")
        fatals = sum(1 for l in logs if l.get("level") == "FATAL")

        # Determine severity
        if fatals > 0:
            insights["severity"] = "critical"
            insights["summary"] = f"CRITICAL: {fatals} fatal errors found"
        elif errors > 20:
            insights["severity"] = "high"
            insights["summary"] = f"HIGH: {errors} errors detected"
        elif errors > 5:
            insights["severity"] = "medium"
            insights["summary"] = f"MEDIUM: {errors} errors found"
        else:
            insights["summary"] = f"Analyzed {total} logs"

        # Generate recommendations
        for pattern in patterns[:3]:
            if pattern["type"] == "repeated_error":
                insights["recommendations"].append(
                    f"Investigate repeated error on {len(pattern['hosts'])} hosts"
                )
            elif pattern["type"] == "burst":
                insights["recommendations"].append(
                    f"Check event at {pattern['time']} ({pattern['count']} logs)"
                )

        return insights


class CephServiceTranslator:
    """Translate Ceph service names to systemd service names"""

    @staticmethod
    def translate_service_name(service_name: str) -> str:
        """Translate Ceph service names to systemd service names

        Examples:
        - osd.12 -> ceph-osd@12.service
        - mon.hostname -> ceph-mon@hostname.service
        - mgr.node1 -> ceph-mgr@node1.service
        """
        import re

        # Handle Ceph OSD services: osd.12 -> ceph-osd@12.service
        osd_match = re.match(r"^osd\.(\d+)$", service_name)
        if osd_match:
            osd_id = osd_match.group(1)
            return f"ceph-osd@{osd_id}.service"

        # Handle Ceph MON services: mon.hostname -> ceph-mon@hostname.service
        mon_match = re.match(r"^mon\.(.+)$", service_name)
        if mon_match:
            mon_id = mon_match.group(1)
            return f"ceph-mon@{mon_id}.service"

        # Handle Ceph MGR services: mgr.hostname -> ceph-mgr@hostname.service
        mgr_match = re.match(r"^mgr\.(.+)$", service_name)
        if mgr_match:
            mgr_id = mgr_match.group(1)
            return f"ceph-mgr@{mgr_id}.service"

        # Handle Ceph MDS services: mds.hostname -> ceph-mds@hostname.service
        mds_match = re.match(r"^mds\.(.+)$", service_name)
        if mds_match:
            mds_id = mds_match.group(1)
            return f"ceph-mds@{mds_id}.service"

        # Handle Ceph RGW services: rgw.hostname -> ceph-radosgw@hostname.service
        rgw_match = re.match(r"^rgw\.(.+)$", service_name)
        if rgw_match:
            rgw_id = rgw_match.group(1)
            return f"ceph-radosgw@{rgw_id}.service"

        # If no translation needed, return as-is (might already be systemd format)
        return service_name

    @staticmethod
    def detect_ceph_services_in_text(text: str) -> List[str]:
        """Detect Ceph service references in natural language text"""
        import re

        services = []

        # Look for patterns like "osd.12", "mon.host1", etc.
        ceph_service_pattern = r"\b(osd|mon|mgr|mds|rgw)\.[\w\-\.]+\b"
        matches = re.findall(ceph_service_pattern, text, re.IGNORECASE)

        for match in matches:
            full_match = re.search(
                rf"\b{re.escape(match)}\.[\w\-\.]+\b", text, re.IGNORECASE
            )
            if full_match:
                services.append(full_match.group())

        return services


class CephDebugTemplates:
    """Pre-built templates for common Ceph debugging scenarios"""

    @staticmethod
    def get_templates() -> Dict[str, Dict]:
        """Get all available debug templates"""
        return {
            "osd_health_check": {
                "name": "OSD Health Check",
                "description": "Check for OSD failures, flapping, and performance issues",
                "query": {
                    "where": {
                        "_and": [
                            {"_SYSTEMD_UNIT": {"_regex": "ceph-osd@.*"}},
                            {"PRIORITY": {"_lte": 4}},
                        ]
                    }
                },
                "hours_back": 24,
                "limit": 100,
            },
            "cluster_status_errors": {
                "name": "Cluster Status Errors",
                "description": "Find critical cluster-wide errors and warnings",
                "query": {
                    "where": {
                        "_and": [
                            {"_SYSTEMD_UNIT": {"_contains": "ceph-mon"}},
                            {"PRIORITY": {"_lte": 3}},
                            {"MESSAGE": {"_regex": "(error|fail|critical|emergency)"}},
                        ]
                    }
                },
                "hours_back": 48,
                "limit": 50,
            },
            "slow_requests": {
                "name": "Slow Request Analysis",
                "description": "Identify slow operations and blocked requests",
                "query": {
                    "where": {
                        "_and": [
                            {"MESSAGE": {"_contains": "slow request"}},
                            {"PRIORITY": {"_lte": 5}},
                        ]
                    }
                },
                "hours_back": 12,
                "limit": 200,
            },
            "pg_issues": {
                "name": "Placement Group Issues",
                "description": "Find PG-related problems: inconsistent, incomplete, degraded",
                "query": {
                    "where": {
                        "_and": [
                            {"MESSAGE": {"_regex": "(pg|placement.?group)"}},
                            {
                                "MESSAGE": {
                                    "_regex": "(inconsistent|incomplete|degraded|stuck|unclean)"
                                }
                            },
                            {"PRIORITY": {"_lte": 4}},
                        ]
                    }
                },
                "hours_back": 72,
                "limit": 100,
            },
            "network_errors": {
                "name": "Network Connectivity Issues",
                "description": "Detect network timeouts, connection failures, and heartbeat issues",
                "query": {
                    "where": {
                        "_and": [
                            {
                                "MESSAGE": {
                                    "_regex": "(network|connection|timeout|heartbeat|unreachable)"
                                }
                            },
                            {"PRIORITY": {"_lte": 4}},
                        ]
                    }
                },
                "hours_back": 24,
                "limit": 150,
            },
            "mon_election": {
                "name": "Monitor Election Issues",
                "description": "Check for monitor election problems and quorum issues",
                "query": {
                    "where": {
                        "_and": [
                            {"_SYSTEMD_UNIT": {"_contains": "ceph-mon"}},
                            {"MESSAGE": {"_regex": "(election|quorum|leader|paxos)"}},
                            {"PRIORITY": {"_lte": 5}},
                        ]
                    }
                },
                "hours_back": 24,
                "limit": 100,
            },
            "storage_errors": {
                "name": "Storage Hardware Errors",
                "description": "Find disk errors, SMART failures, and storage subsystem issues",
                "query": {
                    "where": {
                        "_and": [
                            {
                                "MESSAGE": {
                                    "_regex": "(disk|storage|smart|hardware|device)"
                                }
                            },
                            {"MESSAGE": {"_regex": "(error|fail|abort|timeout)"}},
                            {"PRIORITY": {"_lte": 4}},
                        ]
                    }
                },
                "hours_back": 168,  # 1 week for hardware issues
                "limit": 100,
            },
            "kernel_ceph_errors": {
                "name": "Kernel Ceph Issues",
                "description": "Check kernel-level Ceph messages and errors",
                "query": {
                    "where": {
                        "_and": [
                            {"_TRANSPORT": {"_eq": "kernel"}},
                            {"MESSAGE": {"_regex": "(ceph|rbd|rados)"}},
                            {"PRIORITY": {"_lte": 4}},
                        ]
                    }
                },
                "hours_back": 48,
                "limit": 100,
            },
            "rbd_mapping_issues": {
                "name": "RBD Mapping Problems",
                "description": "Find RBD image mapping/unmapping issues and client problems",
                "query": {
                    "where": {
                        "_and": [
                            {"MESSAGE": {"_contains": "rbd"}},
                            {"MESSAGE": {"_regex": "(map|unmap|mount|unmount|client)"}},
                            {"PRIORITY": {"_lte": 5}},
                        ]
                    }
                },
                "hours_back": 24,
                "limit": 100,
            },
            "recent_startup": {
                "name": "Recent Service Startups",
                "description": "Check recent Ceph service startups and initialization",
                "query": {
                    "where": {
                        "_and": [
                            {"_SYSTEMD_UNIT": {"_regex": "ceph-.*"}},
                            {"MESSAGE": {"_regex": "(start|init|boot|mount|active)"}},
                            {"PRIORITY": {"_lte": 6}},
                        ]
                    }
                },
                "hours_back": 6,
                "limit": 200,
            },
            "specific_osd_analysis": {
                "name": "Specific OSD Analysis (Ceph-friendly syntax)",
                "description": "Analyze specific OSD using natural Ceph syntax (e.g., 'osd.12')",
                "query": {
                    "where": {
                        "_and": [
                            {"_SYSTEMD_UNIT": {"_contains": "ceph-osd@12"}},
                            {"PRIORITY": {"_lte": 5}},
                        ]
                    }
                },
                "hours_back": 48,
                "limit": 150,
                "user_friendly_example": "Search for 'osd.12 issues' - automatically translates to systemd service name",
            },
            "mon_specific_debugging": {
                "name": "Monitor Service Debugging (Ceph-friendly syntax)",
                "description": "Debug specific monitor using natural Ceph syntax (e.g., 'mon.node1')",
                "query": {
                    "where": {
                        "_and": [
                            {"_SYSTEMD_UNIT": {"_contains": "ceph-mon@node1"}},
                            {"PRIORITY": {"_lte": 4}},
                            {
                                "MESSAGE": {
                                    "_regex": "(error|warn|fail|election|quorum)"
                                }
                            },
                        ]
                    }
                },
                "hours_back": 24,
                "limit": 100,
                "user_friendly_example": "Search for 'mon.node1 election problems' - auto-translates service names",
            },
            "ceph_service_translation_showcase": {
                "name": "Ceph Service Translation Examples",
                "description": "Showcase automatic translation of Ceph service names to systemd format",
                "examples": {
                    "osd.12": "Translates to ceph-osd@12.service",
                    "mon.hostname": "Translates to ceph-mon@hostname.service",
                    "mgr.node1": "Translates to ceph-mgr@node1.service",
                    "mds.fs-node": "Translates to ceph-mds@fs-node.service",
                    "rgw.gateway": "Translates to ceph-radosgw@gateway.service",
                },
                "usage_examples": [
                    "Search: 'osd.5 slow requests' → Automatically finds ceph-osd@5.service logs",
                    "Search: 'mon.ceph01 election' → Automatically finds ceph-mon@ceph01.service logs",
                    "Search: 'mgr.primary errors' → Automatically finds ceph-mgr@primary.service logs",
                ],
                "query": {
                    "where": {
                        "_and": [
                            {
                                "_SYSTEMD_UNIT": {
                                    "_regex": "ceph-(osd|mon|mgr|mds|radosgw)@.*"
                                }
                            },
                            {"PRIORITY": {"_lte": 6}},
                        ]
                    }
                },
                "hours_back": 12,
                "limit": 100,
            },
        }

    @staticmethod
    def get_template_by_scenario(scenario: str) -> Optional[Dict]:
        """Get a specific template by scenario name"""
        templates = CephDebugTemplates.get_templates()
        return templates.get(scenario)

    @staticmethod
    def list_scenarios() -> List[str]:
        """List all available debug scenarios"""
        return list(CephDebugTemplates.get_templates().keys())

    @staticmethod
    def search_templates(keyword: str) -> List[Dict]:
        """Search templates by keyword in name or description"""
        templates = CephDebugTemplates.get_templates()
        results = []

        keyword_lower = keyword.lower()
        for template_id, template in templates.items():
            if (
                keyword_lower in template["name"].lower()
                or keyword_lower in template["description"].lower()
            ):
                results.append({"id": template_id, "template": template})

        return results


class ServerIDDetector:
    """Auto-detect available server IDs and suggest optimal filters"""

    def __init__(self, client):
        self.client = client
        self.server_cache = {}
        self.cache_timestamp = None
        self.cache_ttl = 3600  # 1 hour cache

    async def detect_servers(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Detect all available server IDs from recent logs"""

        # Check cache
        if (
            not force_refresh
            and self.cache_timestamp
            and (datetime.now() - self.cache_timestamp).seconds < self.cache_ttl
        ):
            return self.server_cache

        # Query recent logs to find server IDs
        start_time, end_time = calculate_time_range(24)
        detection_query = {
            "type": "query",
            "start": start_time,
            "end": end_time,
            "query": {
                "where": {"CROIT_SERVER_ID": {"_exists": True}},
                "limit": LOG_ANALYSIS_SAMPLE_SIZE,  # Larger sample for server detection
            },
        }

        try:
            logs = await self.client._execute_http_query(detection_query)

            server_info = self._analyze_server_distribution(logs)
            self.server_cache = server_info
            self.cache_timestamp = datetime.now()

            return server_info

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            # Network errors during server detection
            logger.error(f"Server detection failed - network error: {e}")
            return {}
        except (KeyError, ValueError, TypeError) as e:
            # Data parsing errors
            logger.error(f"Server detection failed - data error: {e}")
            return {}

    def _analyze_server_distribution(self, logs: List[Dict]) -> Dict[str, Any]:
        """Analyze server distribution from logs"""
        server_counts = Counter()
        server_services = defaultdict(set)
        server_hostnames = {}

        for log in logs:
            # Try both field names
            server_id = log.get("CROIT_SERVERID") or log.get("CROIT_SERVER_ID")
            if server_id:
                server_counts[str(server_id)] += 1

                # Track services per server
                unit = log.get("_SYSTEMD_UNIT", "unknown")
                server_services[str(server_id)].add(unit)

                # Track hostnames
                hostname = log.get("_HOSTNAME")
                if hostname and server_id not in server_hostnames:
                    server_hostnames[str(server_id)] = hostname

        # Generate server analysis
        total_logs = len(logs)
        servers = {}

        for server_id, count in server_counts.items():
            servers[server_id] = {
                "log_count": count,
                "log_percentage": (
                    round((count / total_logs) * 100, 1) if total_logs > 0 else 0
                ),
                "services": list(server_services[server_id]),
                "hostname": server_hostnames.get(server_id, "unknown"),
                "active": count > 10,  # Consider active if > 10 logs in 24h
            }

        return {
            "servers": servers,
            "total_servers": len(servers),
            "most_active": (
                max(server_counts.keys(), key=server_counts.get)
                if server_counts
                else None
            ),
            "detection_timestamp": datetime.now().isoformat(),
            "logs_analyzed": total_logs,
        }

    def suggest_server_filter(
        self, intent: str, server_info: Dict = None
    ) -> Optional[Dict]:
        """Suggest server-specific filters based on intent"""
        if not server_info:
            return None

        servers = server_info.get("servers", {})
        if not servers:
            return None

        intent_lower = intent.lower()

        # Specific server mentioned
        for server_id in servers.keys():
            if (
                f"server {server_id}" in intent_lower
                or f"node {server_id}" in intent_lower
            ):
                return {
                    "type": "specific_server",
                    "server_id": server_id,
                    "filter": {"CROIT_SERVERID": {"_eq": server_id}},
                    "reason": f"User mentioned server {server_id}",
                }

        # Hostname mentioned
        for server_id, info in servers.items():
            hostname = info.get("hostname", "").lower()
            if hostname and hostname != "unknown" and hostname in intent_lower:
                return {
                    "type": "hostname_match",
                    "server_id": server_id,
                    "hostname": hostname,
                    "filter": {"CROIT_SERVERID": {"_eq": server_id}},
                    "reason": f"User mentioned hostname {hostname}",
                }

        # Service-specific suggestions
        if "osd" in intent_lower:
            osd_servers = [
                server_id
                for server_id, info in servers.items()
                if any("ceph-osd" in service for service in info.get("services", []))
            ]
            if len(osd_servers) == 1:
                return {
                    "type": "service_specific",
                    "server_id": osd_servers[0],
                    "filter": {"CROIT_SERVERID": {"_eq": osd_servers[0]}},
                    "reason": f"Only server {osd_servers[0]} runs OSD services",
                }

        # Performance-based suggestions
        if any(
            word in intent_lower for word in ["slow", "performance", "issue", "problem"]
        ):
            # Suggest the most active server for performance issues
            most_active = server_info.get("most_active")
            if most_active:
                return {
                    "type": "performance_focus",
                    "server_id": most_active,
                    "filter": {"CROIT_SERVERID": {"_eq": most_active}},
                    "reason": f'Server {most_active} is most active ({servers[most_active]["log_percentage"]}% of logs)',
                }

        return None

    def get_server_summary(self, server_info: Dict = None) -> str:
        """Generate human-readable server summary"""
        if not server_info or not server_info.get("servers"):
            return "No servers detected in recent logs"

        servers = server_info["servers"]
        total = server_info["total_servers"]
        most_active = server_info.get("most_active")

        lines = [f"🖥️ Detected {total} active server(s):"]

        for server_id, info in sorted(servers.items()):
            hostname = info.get("hostname", "unknown")
            log_count = info.get("log_count", 0)
            percentage = info.get("log_percentage", 0)
            services = len(info.get("services", []))

            status = "🟢" if info.get("active", False) else "🟡"
            lines.append(
                f"{status} Server {server_id} ({hostname}): {log_count:,} logs ({percentage}%), {services} services"
            )

        if most_active:
            lines.append(f"📈 Most active: Server {most_active}")

        return "\n".join(lines)


class LogTransportAnalyzer:
    """Analyze available log transports and debug kernel log availability"""

    def __init__(self, client):
        self.client = client

    async def analyze_transports(self, hours_back: int = 24) -> Dict[str, Any]:
        """Analyze what transport types are available in the logs"""

        # Query recent logs to analyze transports
        start_time, end_time = calculate_time_range(hours_back)
        analysis_query = {
            "type": "query",
            "start": start_time,
            "end": end_time,
            "query": {
                "where": {
                    "_search": ""  # Get any logs to analyze transport distribution
                },
                "limit": LOG_MEDIUM_SAMPLE_SIZE,  # Larger sample for transport analysis
            },
        }

        try:
            logs = await self.client._execute_http_query(analysis_query)
            return self._analyze_transport_distribution(logs)

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            # Network errors during transport analysis
            logger.error(f"Transport analysis failed - network error: {e}")
            return {}
        except (KeyError, ValueError, TypeError) as e:
            # Data parsing/analysis errors
            logger.error(f"Transport analysis failed - data error: {e}")
            return {}

    def _analyze_transport_distribution(self, logs: List[Dict]) -> Dict[str, Any]:
        """Analyze transport field distribution in logs"""
        transport_counts = Counter()
        transport_priorities = defaultdict(Counter)
        transport_services = defaultdict(set)
        sample_messages = defaultdict(list)

        for log in logs:
            # Check all possible transport field names
            transport = (
                log.get("_TRANSPORT")
                or log.get("TRANSPORT")
                or log.get("transport")
                or "unknown"
            )

            transport_counts[transport] += 1

            # Track priority distribution per transport
            priority = log.get("PRIORITY", 6)
            transport_priorities[transport][priority] += 1

            # Track services per transport
            service = log.get("_SYSTEMD_UNIT", log.get("SYSLOG_IDENTIFIER", "unknown"))
            transport_services[transport].add(service)

            # Collect sample messages (first 3 per transport)
            if len(sample_messages[transport]) < 3:
                message = log.get("MESSAGE", "")[:100]
                if message:
                    sample_messages[transport].append(message)

        # Generate analysis
        total_logs = len(logs)
        analysis = {
            "total_logs_analyzed": total_logs,
            "transports_found": len(transport_counts),
            "transport_distribution": dict(transport_counts),
            "analysis_timestamp": datetime.now().isoformat(),
        }

        # Detailed transport info
        transport_details = {}
        for transport, count in transport_counts.items():
            priority_dist = dict(transport_priorities[transport])
            services = list(transport_services[transport])

            transport_details[transport] = {
                "log_count": count,
                "percentage": (
                    round((count / total_logs) * 100, 1) if total_logs > 0 else 0
                ),
                "priority_distribution": priority_dist,
                "services": services[:10],  # Top 10 services
                "sample_messages": sample_messages[transport],
                "critical_logs": priority_dist.get(0, 0)
                + priority_dist.get(1, 0)
                + priority_dist.get(2, 0)
                + priority_dist.get(3, 0),
            }

        analysis["transport_details"] = transport_details

        # Kernel log investigation
        kernel_transports = [
            t for t in transport_counts.keys() if "kernel" in t.lower()
        ]
        syslog_count = transport_counts.get("syslog", 0)
        journal_count = transport_counts.get("journal", 0)

        analysis["kernel_investigation"] = {
            "kernel_transports_found": kernel_transports,
            "kernel_direct_count": transport_counts.get("kernel", 0),
            "syslog_count": syslog_count,
            "journal_count": journal_count,
            "recommendation": self._recommend_kernel_query_strategy(transport_counts),
        }

        return analysis

    def _recommend_kernel_query_strategy(self, transport_counts: Counter) -> str:
        """Recommend the best strategy to find kernel logs"""
        kernel_direct = transport_counts.get("kernel", 0)
        syslog_count = transport_counts.get("syslog", 0)
        journal_count = transport_counts.get("journal", 0)

        if kernel_direct > 0:
            return "Use _TRANSPORT: 'kernel' - direct kernel logs found"
        elif syslog_count > 0:
            return "Try _TRANSPORT: 'syslog' with SYSLOG_IDENTIFIER: 'kernel' - kernel logs likely in syslog"
        elif journal_count > 0:
            return "Try _TRANSPORT: 'journal' with systemd journal filtering - kernel logs in journal"
        else:
            available = list(transport_counts.keys())
            return f"No kernel transport found. Available: {available}. Try SYSLOG_IDENTIFIER filtering instead."

    async def find_kernel_logs(
        self, hours_back: int = 24, limit: int = 100
    ) -> Dict[str, Any]:
        """Try multiple strategies to find kernel logs"""
        strategies = [
            {
                "name": "Direct kernel transport",
                "query": {
                    "where": {
                        "_and": [
                            {"_TRANSPORT": {"_eq": "kernel"}},
                            {"PRIORITY": {"_lte": 5}},
                        ]
                    }
                },
            },
            {
                "name": "Syslog with kernel identifier",
                "query": {
                    "where": {
                        "_and": [
                            {"_TRANSPORT": {"_eq": "syslog"}},
                            {"SYSLOG_IDENTIFIER": {"_eq": "kernel"}},
                            {"PRIORITY": {"_lte": 5}},
                        ]
                    }
                },
            },
            {
                "name": "Kernel in message content",
                "query": {
                    "where": {
                        "_and": [
                            {"MESSAGE": {"_contains": "kernel"}},
                            {"PRIORITY": {"_lte": 4}},
                        ]
                    }
                },
            },
            {
                "name": "Hardware/driver messages",
                "query": {
                    "where": {
                        "_and": [
                            {
                                "MESSAGE": {
                                    "_regex": "(hardware|driver|device|disk|network)"
                                }
                            },
                            {"PRIORITY": {"_lte": 4}},
                        ]
                    }
                },
            },
        ]

        results = {}

        for strategy in strategies:
            try:
                start_time, end_time = calculate_time_range(hours_back)
                query = {
                    "type": "query",
                    "start": start_time,
                    "end": end_time,
                    "query": {**strategy["query"], "limit": limit},
                }

                logs = await self.client._execute_http_query(query)

                results[strategy["name"]] = {
                    "success": len(logs) > 0,
                    "log_count": len(logs),
                    "sample_messages": [
                        log.get("MESSAGE", "")[:100] for log in logs[:3]
                    ],
                    "transports_found": list(
                        set(log.get("_TRANSPORT", "unknown") for log in logs)
                    ),
                    "query_used": strategy["query"],
                }

            except Exception as e:
                results[strategy["name"]] = {
                    "success": False,
                    "error": str(e),
                    "query_used": strategy["query"],
                }

        return {
            "kernel_search_results": results,
            "recommendations": self._generate_kernel_recommendations(results),
            "search_timestamp": datetime.now().isoformat(),
        }

    def _generate_kernel_recommendations(self, results: Dict) -> List[str]:
        """Generate recommendations based on kernel search results"""
        recommendations = []

        successful_strategies = [
            name for name, result in results.items() if result.get("success", False)
        ]

        if successful_strategies:
            best_strategy = max(
                successful_strategies, key=lambda x: results[x].get("log_count", 0)
            )
            recommendations.append(f"✅ Best kernel log strategy: {best_strategy}")
            recommendations.append(
                f"Found {results[best_strategy]['log_count']} logs with this method"
            )
        else:
            recommendations.append("❌ No kernel logs found with standard methods")
            recommendations.append(
                "💡 Try checking VictoriaLogs configuration for kernel log ingestion"
            )
            recommendations.append(
                "🔍 Consider using broader searches with hardware/system keywords"
            )

        return recommendations


class LogSummaryEngine:
    """Intelligent log summarization and critical event prioritization"""

    def __init__(self):
        self.critical_keywords = [
            "failed",
            "error",
            "crash",
            "panic",
            "fatal",
            "abort",
            "exception",
            "timeout",
            "unreachable",
            "down",
            "offline",
            "corruption",
            "loss",
        ]
        self.priority_levels = {
            0: "EMERGENCY",
            1: "ALERT",
            2: "CRITICAL",
            3: "ERROR",
            4: "WARNING",
            5: "NOTICE",
            6: "INFO",
            7: "DEBUG",
        }

    def summarize_logs(self, logs: List[Dict], max_details: int = 10) -> Dict:
        """Create intelligent summary with critical events first"""
        if not logs:
            return {
                "summary": "No logs found",
                "total_logs": 0,
                "critical_events": [],
                "trends": {},
                "recommendations": [],
            }

        total_logs = len(logs)

        # Priority analysis
        priority_stats = self._analyze_priorities(logs)

        # Service analysis
        service_stats = self._analyze_services(logs)

        # Critical events (prioritized)
        critical_events = self._extract_critical_events(logs, max_details)

        # Time-based trends
        trends = self._analyze_trends(logs)

        # Generate summary text
        summary_text = self._generate_summary_text(
            total_logs, priority_stats, service_stats, critical_events
        )

        # Smart recommendations
        recommendations = self._generate_recommendations(
            priority_stats, service_stats, critical_events, trends
        )

        return {
            "summary": summary_text,
            "total_logs": total_logs,
            "priority_breakdown": priority_stats,
            "service_breakdown": service_stats,
            "critical_events": critical_events,
            "trends": trends,
            "recommendations": recommendations,
            "time_range": self._get_time_range(logs),
        }

    def _analyze_priorities(self, logs: List[Dict]) -> Dict:
        """Analyze log priority distribution"""
        priority_counts = Counter()
        for log in logs:
            priority = log.get("PRIORITY", 6)  # Default to INFO if missing
            priority_name = self.priority_levels.get(priority, f"LEVEL_{priority}")
            priority_counts[priority_name] += 1

        return dict(priority_counts)

    def _analyze_services(self, logs: List[Dict]) -> Dict:
        """Analyze service/unit distribution"""
        service_counts = Counter()
        for log in logs:
            unit = log.get("_SYSTEMD_UNIT", log.get("SYSLOG_IDENTIFIER", "unknown"))
            service_counts[unit] += 1

        return dict(service_counts.most_common(10))  # Top 10 services

    def _extract_critical_events(self, logs: List[Dict], max_events: int) -> List[Dict]:
        """Extract and prioritize critical events"""
        critical_logs = []

        for log in logs:
            priority = log.get("PRIORITY", 6)
            message = log.get("MESSAGE", "").lower()

            # Score criticality (lower = more critical)
            criticality_score = priority * 10  # Base on priority

            # Boost score for critical keywords
            for keyword in self.critical_keywords:
                if keyword in message:
                    criticality_score -= 20

            # Boost score for OSD-specific issues
            if "osd" in message and any(
                word in message for word in ["failed", "down", "crash"]
            ):
                criticality_score -= 15

            critical_logs.append(
                {
                    "log": log,
                    "score": criticality_score,
                    "timestamp": log.get("__REALTIME_TIMESTAMP", ""),
                    "service": log.get("_SYSTEMD_UNIT", "unknown"),
                    "priority": self.priority_levels.get(priority, f"LEVEL_{priority}"),
                    "message_preview": (
                        log.get("MESSAGE", "")[:100] + "..."
                        if len(log.get("MESSAGE", "")) > 100
                        else log.get("MESSAGE", "")
                    ),
                }
            )

        # Sort by criticality (lowest score = most critical)
        critical_logs.sort(key=lambda x: x["score"])

        return critical_logs[:max_events]

    def _analyze_trends(self, logs: List[Dict]) -> Dict:
        """Analyze time-based trends and patterns"""
        if not logs:
            return {}

        # Group by hour for trend analysis
        hourly_counts = Counter()
        service_trends = defaultdict(Counter)

        for log in logs:
            timestamp = log.get("__REALTIME_TIMESTAMP")
            if timestamp:
                try:
                    # Convert microseconds to datetime
                    dt = datetime.fromtimestamp(int(timestamp) / 1000000)
                    hour_key = dt.strftime("%Y-%m-%d %H:00")
                    hourly_counts[hour_key] += 1

                    service = log.get("_SYSTEMD_UNIT", "unknown")
                    service_trends[service][hour_key] += 1
                except (ValueError, OverflowError):
                    continue

        # Find peak hours
        peak_hours = hourly_counts.most_common(3)

        return {
            "hourly_distribution": dict(hourly_counts),
            "peak_hours": peak_hours,
            "active_services": len(service_trends),
            "busiest_service": (
                max(
                    service_trends.keys(), key=lambda s: sum(service_trends[s].values())
                )
                if service_trends
                else None
            ),
        }

    def _generate_summary_text(
        self,
        total_logs: int,
        priority_stats: Dict,
        service_stats: Dict,
        critical_events: List,
    ) -> str:
        """Generate human-readable summary"""
        lines = []
        lines.append(f"📊 **Log Analysis Summary** - {total_logs:,} total entries")

        # Priority summary
        if priority_stats:
            critical_count = (
                priority_stats.get("CRITICAL", 0)
                + priority_stats.get("EMERGENCY", 0)
                + priority_stats.get("ALERT", 0)
            )
            error_count = priority_stats.get("ERROR", 0)
            warning_count = priority_stats.get("WARNING", 0)

            if critical_count > 0:
                lines.append(f"🚨 {critical_count} critical/emergency events")
            if error_count > 0:
                lines.append(f"❌ {error_count} errors")
            if warning_count > 0:
                lines.append(f"⚠️ {warning_count} warnings")

        # Top services
        if service_stats:
            top_service = list(service_stats.keys())[0]
            top_count = service_stats[top_service]
            lines.append(f"🔧 Most active: {top_service} ({top_count} logs)")

        # Critical events preview
        if critical_events:
            lines.append(f"⚡ {len(critical_events)} high-priority events identified")

        return "\n".join(lines)

    def _generate_recommendations(
        self,
        priority_stats: Dict,
        service_stats: Dict,
        critical_events: List,
        trends: Dict,
    ) -> List[str]:
        """Generate actionable recommendations"""
        recommendations = []

        # Priority-based recommendations
        critical_total = (
            priority_stats.get("CRITICAL", 0)
            + priority_stats.get("EMERGENCY", 0)
            + priority_stats.get("ALERT", 0)
        )
        if critical_total > 5:
            recommendations.append(
                f"🚨 Immediate attention needed: {critical_total} critical events"
            )

        error_count = priority_stats.get("ERROR", 0)
        if error_count > 20:
            recommendations.append(
                f"🔍 Investigate error patterns: {error_count} errors found"
            )

        # Service-based recommendations
        if service_stats:
            ceph_services = {
                k: v for k, v in service_stats.items() if "ceph" in k.lower()
            }
            if ceph_services:
                total_ceph_logs = sum(ceph_services.values())
                if total_ceph_logs > len(service_stats) * 0.7:  # Ceph dominates logs
                    recommendations.append(
                        "🐙 High Ceph activity detected - monitor cluster health"
                    )

        # Critical events recommendations
        if critical_events:
            osd_issues = [
                e for e in critical_events if "osd" in e["message_preview"].lower()
            ]
            if len(osd_issues) > 3:
                recommendations.append(
                    "💾 Multiple OSD issues detected - check storage health"
                )

        # Trends recommendations
        if trends.get("peak_hours"):
            recommendations.append(
                f"📈 Peak activity: {trends['peak_hours'][0][0]} - review load patterns"
            )

        return recommendations

    def _get_time_range(self, logs: List[Dict]) -> Dict:
        """Calculate actual time range of logs"""
        timestamps = []
        for log in logs:
            timestamp = log.get("__REALTIME_TIMESTAMP")
            if timestamp:
                try:
                    timestamps.append(int(timestamp) / 1000000)
                except (ValueError, OverflowError):
                    continue

        if not timestamps:
            return {}

        start_time = min(timestamps)
        end_time = max(timestamps)

        return {
            "start": datetime.fromtimestamp(start_time).isoformat(),
            "end": datetime.fromtimestamp(end_time).isoformat(),
            "duration_hours": round((end_time - start_time) / 3600, 2),
        }


async def _extract_logs_from_zip(zip_data: bytes) -> List[Dict]:
    """Extract log entries from ZIP file"""
    import zipfile
    import io
    import json

    logs = []

    try:
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            for filename in zf.namelist():
                logger.debug(f"Processing ZIP file: {filename}")

                with zf.open(filename) as file:
                    content = file.read().decode("utf-8")
                    lines = content.strip().split("\n")

                    for line_num, line in enumerate(lines):
                        if line.strip():
                            try:
                                log_entry = json.loads(line)
                                logs.append(log_entry)
                            except json.JSONDecodeError as e:
                                logger.warning(
                                    f"Failed to parse log line {line_num}: {e}"
                                )
                                # Add as raw text if JSON parsing fails
                                logs.append(
                                    {
                                        "raw_message": line,
                                        "parse_error": str(e),
                                        "line_number": line_num,
                                    }
                                )

    except zipfile.BadZipFile as e:
        # Invalid or corrupt ZIP file
        logger.error(f"Failed to extract logs - invalid ZIP file: {e}")
    except (OSError, IOError) as e:
        # File I/O errors
        logger.error(f"Failed to extract logs - I/O error: {e}")
    except json.JSONDecodeError as e:
        # Invalid JSON in ZIP content
        logger.error(f"Failed to extract logs - invalid JSON: {e}")

    return logs


async def _execute_croit_http_export(
    host: str, port: int, api_token: str, use_ssl: bool, query: Dict
) -> Dict:
    """Execute Croit log query via HTTP /api/logs/export endpoint"""
    import aiohttp

    # Build HTTP URL
    http_protocol = "https" if use_ssl else "http"
    url = f"{http_protocol}://{host}:{port}/api/logs/export"

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    params = {
        "format": "RAW",  # Use RAW format as discovered
        "query": json.dumps(query),
    }

    logger.debug(f"HTTP GET {url}")
    logger.debug(f"Params: {params}")
    logger.debug(f"Headers: {headers}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers) as response:
                logger.debug(f"HTTP response status: {response.status}")
                logger.debug(f"HTTP response headers: {dict(response.headers)}")

                if response.status == 200:
                    response_json = await response.json()
                    logger.debug(f"HTTP response JSON: {response_json}")

                    # The response contains a download URL to a ZIP file
                    download_url = response_json.get("url")
                    if download_url:
                        logger.debug(f"Downloading logs from: {download_url}")

                        # Download and extract the ZIP file
                        async with session.get(
                            download_url,
                            headers={"Authorization": f"Bearer {api_token}"},
                        ) as zip_response:
                            if zip_response.status == 200:
                                zip_data = await zip_response.read()
                                logger.debug(
                                    f"Downloaded ZIP file: {len(zip_data)} bytes"
                                )

                                # Extract logs from ZIP
                                logs = await _extract_logs_from_zip(zip_data)
                                logger.debug(
                                    f"Extracted {len(logs)} log entries from ZIP"
                                )

                                return {
                                    "logs": logs,
                                    "control_messages": [
                                        {
                                            "type": "success",
                                            "message": f"Downloaded {len(logs)} logs",
                                        }
                                    ],
                                    "download_info": response_json,
                                }
                            else:
                                logger.error(
                                    f"Failed to download logs: {zip_response.status}"
                                )
                                return {
                                    "logs": [],
                                    "control_messages": [
                                        {
                                            "type": "error",
                                            "message": f"Download failed: {zip_response.status}",
                                        }
                                    ],
                                }
                    else:
                        logger.error("No download URL in response")
                        return {
                            "logs": [],
                            "control_messages": [
                                {"type": "error", "message": "No download URL"}
                            ],
                        }
                else:
                    error_text = await response.text()
                    logger.error(f"HTTP query failed: {response.status} - {error_text}")
                    return {
                        "logs": [],
                        "control_messages": [
                            {
                                "type": "error",
                                "message": f"HTTP {response.status}: {error_text}",
                            }
                        ],
                    }

    except aiohttp.ClientError as e:
        # Network/connection errors
        logger.error(f"HTTP query failed - connection error: {e}")
        return {
            "logs": [],
            "control_messages": [
                {"type": "error", "message": f"Connection error: {str(e)}"}
            ],
        }
    except asyncio.TimeoutError:
        # Request timeout
        logger.error("HTTP query failed - timeout")
        return {
            "logs": [],
            "control_messages": [{"type": "error", "message": "Request timeout"}],
        }
    except json.JSONDecodeError as e:
        # Invalid JSON response
        logger.error(f"HTTP query failed - invalid JSON: {e}")
        return {
            "logs": [],
            "control_messages": [
                {"type": "error", "message": f"Invalid JSON response: {str(e)}"}
            ],
        }


async def _execute_croit_websocket(
    host: str, port: int, api_token: str, use_ssl: bool, query: Dict
) -> List[Dict]:
    """Execute direct Croit WebSocket query with VictoriaLogs JSON format"""
    import json
    import asyncio
    import websockets

    # Build WebSocket URL with token authentication
    ws_protocol = "wss" if use_ssl else "ws"
    if api_token:
        ws_url = f"{ws_protocol}://{host}:{port}/api/logs?token={api_token}"
        logger.debug(f"Using query param authentication")
    else:
        ws_url = f"{ws_protocol}://{host}:{port}/api/logs"
        logger.warning("No API token provided for WebSocket authentication")

    logs = []
    control_messages = []

    logger.debug(f"Attempting WebSocket connection to: {ws_url}")

    try:
        async with websockets.connect(ws_url, ping_interval=20) as websocket:
            logger.debug(f"WebSocket connection established successfully")

            # Send Croit JSON query directly (auth via URL params)
            query_json = json.dumps(query, indent=2)
            logger.debug(f"Sending WebSocket query: {query_json}")
            await websocket.send(query_json)
            logger.debug("Query sent successfully")

            # Collect responses with longer timeout for query param auth
            start_time = asyncio.get_event_loop().time()
            while (
                asyncio.get_event_loop().time() - start_time
            ) < 45:  # Increased timeout
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    if response:
                        logger.debug(f"WebSocket response: {response[:200]}...")

                        # Handle control messages
                        if response == "clear":
                            control_messages.append(
                                {"type": "clear", "message": "Log display cleared"}
                            )
                            logger.debug("Received 'clear' control message")
                        elif response == "empty":
                            control_messages.append(
                                {
                                    "type": "empty",
                                    "message": "No logs found for current query",
                                }
                            )
                            logger.debug(
                                "Received 'empty' control message - no logs found"
                            )
                        elif response == "too_wide":
                            control_messages.append(
                                {
                                    "type": "too_wide",
                                    "message": "Query too broad (>1M logs), please add more filters",
                                }
                            )
                            logger.debug("Received 'too_wide' control message")
                        elif response.startswith("hits:"):
                            try:
                                hits_data = (
                                    json.loads(response[5:].strip())
                                    if response[5:].strip() != "null"
                                    else None
                                )
                                control_messages.append(
                                    {"type": "hits", "data": hits_data}
                                )
                                logger.debug(f"Received hits data: {hits_data}")
                            except json.JSONDecodeError:
                                logger.warning(f"Failed to parse hits data: {response}")
                        elif response.startswith("error:"):
                            error_msg = response[6:].strip()
                            control_messages.append(
                                {"type": "error", "message": error_msg}
                            )
                            logger.error(f"VictoriaLogs error: {error_msg}")
                        else:
                            # Regular log entry
                            try:
                                log_entry = json.loads(response)
                                logs.append(log_entry)
                                logger.debug(
                                    f"Added log entry {len(logs)}: {log_entry.get('timestamp', 'no-timestamp')}"
                                )
                            except json.JSONDecodeError:
                                logger.warning(f"Non-JSON response: {response[:100]}")
                except asyncio.TimeoutError:
                    break
                except websockets.exceptions.ConnectionClosed:
                    break

    except websockets.exceptions.WebSocketException as e:
        # WebSocket protocol errors
        logger.error(f"WebSocket query failed - protocol error: {e}")
        raise
    except (ConnectionError, OSError) as e:
        # Network/connection errors
        logger.error(f"WebSocket query failed - connection error: {e}")
        raise
    except json.JSONDecodeError as e:
        # Invalid JSON in messages
        logger.error(f"WebSocket query failed - invalid JSON: {e}")
        raise

    logger.debug(
        f"WebSocket query completed: {len(logs)} logs, {len(control_messages)} control messages"
    )
    return {"logs": logs, "control_messages": control_messages}


# Integration functions for MCP Server
async def handle_log_search(
    arguments: Dict, host: str, port: int = DEFAULT_HTTP_PORT
) -> Dict[str, Any]:
    """Handle direct VictoriaLogs JSON query"""
    import time
    from datetime import datetime, timedelta

    # Extract where clause
    where_clause = arguments.get("where")
    search_text = arguments.get("_search", "")
    limit = arguments.get("limit", DEFAULT_LOG_LIMIT)
    after = arguments.get("after", 0)
    hours_back = arguments.get("hours_back", 1)
    start_timestamp = arguments.get("start_timestamp")
    end_timestamp = arguments.get("end_timestamp")
    api_token = arguments.get("api_token")
    use_ssl = arguments.get("use_ssl", False)

    # Calculate time range
    if start_timestamp and end_timestamp:
        start = int(start_timestamp)
        end = int(end_timestamp)
    else:
        start, end = calculate_time_range(hours_back)

    # Build where clause
    query_where = where_clause if where_clause else {}

    # Add search text if provided
    if search_text:
        if "_and" in query_where:
            query_where["_and"].append({"_search": search_text})
        elif "_or" in query_where:
            # Wrap in AND with search
            query_where = {"_and": [query_where, {"_search": search_text}]}
        else:
            query_where = {"_and": [query_where, {"_search": search_text}]}

    # Build Croit log export query
    croit_query = {
        "type": "query",
        "start": start,
        "end": end,
        "query": {"where": query_where, "after": after, "limit": limit},
    }

    # Execute query via HTTP (not WebSocket!)
    logger.debug(f"Executing HTTP query to {host}:{port}")
    response = await _execute_croit_http_export(
        host, port, api_token, use_ssl, croit_query
    )
    logs = response.get("logs", [])
    control_messages = response.get("control_messages", [])

    logger.debug(
        f"HTTP response summary: {len(logs)} logs, {len(control_messages)} control messages"
    )
    if control_messages:
        logger.debug(
            f"Control messages received: {[msg.get('type', 'unknown') for msg in control_messages]}"
        )

    # Calculate actual hours searched
    actual_hours_searched = (end - start) / 3600.0

    return {
        "code": 200,
        "result": {
            "logs": logs,
            "total_count": len(logs),
            "control_messages": control_messages,
            "time_range": {
                "start_timestamp": start,
                "end_timestamp": end,
                "hours_searched": actual_hours_searched,
            },
        },
        "debug": {
            "croit_query": croit_query,
            "where_clause": where_clause,
            "time_range_human": f"{datetime.fromtimestamp(start)} to {datetime.fromtimestamp(end)}",
            "timestamp_diff_seconds": end - start,
            "calculated_hours": actual_hours_searched,
            "input_hours_back": hours_back,
        },
    }


async def handle_log_check(
    arguments: Dict, host: str, port: int = DEFAULT_HTTP_PORT
) -> Dict[str, Any]:
    """
    Check log conditions immediately (snapshot) - suitable for LLMs
    Returns results immediately instead of monitoring for a duration
    """

    conditions = arguments.get("conditions", [])
    alert_threshold = arguments.get("threshold", 5)
    time_window = arguments.get("time_window", 300)  # Check last 5 minutes by default
    api_token = arguments.get("api_token")
    use_ssl = arguments.get("use_ssl", False)

    if not conditions:
        return {"code": 400, "error": "Conditions are required"}

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
                "condition": condition,
                "count": result["total_count"],
                "threshold": alert_threshold,
                "triggered": result["total_count"] >= alert_threshold,
                "severity": (
                    result["insights"]["severity"]
                    if result["total_count"] > 0
                    else "none"
                ),
                "timestamp": datetime.now().isoformat(),
            }

            checks.append(check_result)

            if check_result["triggered"]:
                alerts.append(
                    {
                        "condition": condition,
                        "count": result["total_count"],
                        "severity": result["insights"]["severity"],
                        "sample_logs": (
                            result["results"][:3] if result["results"] else []
                        ),
                    }
                )

        return {
            "code": 200,
            "result": {
                "checks": checks,
                "alerts": alerts,
                "summary": f"{len(alerts)} of {len(conditions)} conditions triggered",
                "time_window": f"Last {time_window} seconds",
                "recommendation": (
                    "Run again later to check for changes" if alerts else "All clear"
                ),
            },
        }

    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        # Network errors during log check
        logger.error(f"Log check failed - network error: {e}")
        return {"code": 503, "error": f"Network error: {str(e)}"}
    except (KeyError, ValueError, TypeError) as e:
        # Data/argument errors
        logger.error(f"Log check failed - data error: {e}")
        return {"code": 400, "error": f"Invalid data: {str(e)}"}
    except Exception as e:
        # Unexpected errors
        logger.error(f"Log check failed - unexpected error: {type(e).__name__}: {e}")
        return {"code": 500, "error": str(e)}


# Keep for backwards compatibility but mark as deprecated
async def handle_log_monitor(
    arguments: Dict, host: str, port: int = DEFAULT_HTTP_PORT
) -> Dict[str, Any]:
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
• CROIT_SERVERID: alternative field name for server ID (string/integer) - same as CROIT_SERVER_ID
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
• _nin: value not in list {"CROIT_SERVERID": {"_nin": ["1", "2"]}}

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
  {"CROIT_SERVERID": {"_eq": "1"}}
]}}

2. Kernel logs on server 1:
{"where": {"_and": [
  {"_TRANSPORT": {"_eq": "kernel"}},
  {"PRIORITY": {"_lte": 6}},
  {"CROIT_SERVERID": {"_eq": "1"}}
]}}

3. Kernel logs with error search (note _search is outside where clause):
{
  "where": {"_and": [
    {"_TRANSPORT": {"_eq": "kernel"}},
    {"PRIORITY": {"_lte": 6}},
    {"CROIT_SERVERID": {"_eq": "1"}}
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
  {"CROIT_SERVERID": {"_eq": "1"}}
]}}

3. Multiple priority levels (errors + warnings):
{"where": {"PRIORITY": {"_in": [3, 4]}}}

4. Exclude specific servers from search:
{"where": {"_and": [
  {"_SYSTEMD_UNIT": {"_contains": "ceph-osd"}},
  {"CROIT_SERVERID": {"_not_in": ["1", "2", "3"]}}
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
                    "description": "VictoriaLogs JSON where clause (see examples above)",
                },
                "_search": {
                    "type": "string",
                    "default": "",
                    "description": "Full-text search string (optional) - searches within message content",
                },
                "limit": {
                    "type": "integer",
                    "default": 1000,
                    "description": "Maximum number of logs to return",
                },
                "after": {
                    "type": "integer",
                    "default": 0,
                    "description": "Offset for pagination (number of logs to skip)",
                },
                "hours_back": {
                    "type": "integer",
                    "default": 1,
                    "description": "Hours to search back from now (ignored if timestamps provided)",
                },
                "start_timestamp": {
                    "type": "integer",
                    "description": "Unix timestamp start (optional)",
                },
                "end_timestamp": {
                    "type": "integer",
                    "description": "Unix timestamp end (optional)",
                },
            },
            "required": ["where"],
        },
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
                    "description": "List of conditions to check in natural language",
                },
                "threshold": {
                    "type": "integer",
                    "default": 5,
                    "description": "Number of matching logs to trigger alert (default: 5)",
                },
                "time_window": {
                    "type": "integer",
                    "default": 300,
                    "description": "Time window in seconds to check (default: 300 = 5 min)",
                },
                "api_token": {
                    "type": "string",
                    "description": "Optional API token for authentication",
                },
            },
            "required": ["conditions"],
        },
    },
]
