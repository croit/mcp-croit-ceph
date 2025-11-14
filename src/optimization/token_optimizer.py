#!/usr/bin/env python3
"""
Token optimization module for MCP Croit Ceph.
Provides utilities to reduce token consumption when dealing with large API responses.
"""

import json
import logging
import re
import time
import hashlib
import gzip
import base64
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Cache entry with TTL support."""

    data: Any
    timestamp: float
    ttl: int

    def is_expired(self) -> bool:
        """Check if cache entry is expired."""
        return time.time() > (self.timestamp + self.ttl)


class ResponseCache:
    """Intelligent cache for API responses with TTL and size limits."""

    def __init__(self, max_size: int = 100, default_ttl: int = 300):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: Dict[str, CacheEntry] = {}
        self._access_times: Dict[str, float] = {}

    def _generate_key(self, url: str, method: str, params: Dict = None) -> str:
        """Generate cache key from request parameters."""
        key_data = f"{method.upper()}:{url}"
        if params:
            # Sort params for consistent key generation
            sorted_params = json.dumps(params, sort_keys=True, separators=(",", ":"))
            key_data += f":{sorted_params}"
        return hashlib.md5(key_data.encode()).hexdigest()

    def get(self, url: str, method: str, params: Dict = None) -> Optional[Any]:
        """Get cached response if available and not expired."""
        key = self._generate_key(url, method, params)

        if key not in self._cache:
            return None

        entry = self._cache[key]
        if entry.is_expired():
            del self._cache[key]
            if key in self._access_times:
                del self._access_times[key]
            return None

        # Update access time for LRU
        self._access_times[key] = time.time()
        logger.info(f"Cache hit for {method} {url}")
        return entry.data

    def set(
        self, url: str, method: str, data: Any, params: Dict = None, ttl: int = None
    ) -> None:
        """Cache response data with TTL."""
        key = self._generate_key(url, method, params)

        # Use custom TTL or default
        if ttl is None:
            # Determine TTL based on endpoint type
            if any(pattern in url.lower() for pattern in ["/status", "/health"]):
                ttl = 60  # 1 minute for status/health
            elif any(pattern in url.lower() for pattern in ["/stats", "/metrics"]):
                ttl = 180  # 3 minutes for stats
            elif any(pattern in url.lower() for pattern in ["/list", "/all"]):
                ttl = 600  # 10 minutes for lists
            else:
                ttl = self.default_ttl

        # Remove oldest entries if cache is full
        if len(self._cache) >= self.max_size:
            self._evict_lru()

        self._cache[key] = CacheEntry(data=data, timestamp=time.time(), ttl=ttl)
        self._access_times[key] = time.time()
        logger.info(f"Cached response for {method} {url} (TTL: {ttl}s)")

    def _evict_lru(self) -> None:
        """Evict least recently used entry."""
        if not self._access_times:
            return

        lru_key = min(self._access_times.keys(), key=lambda k: self._access_times[k])
        del self._cache[lru_key]
        del self._access_times[lru_key]
        logger.info(f"Evicted LRU cache entry: {lru_key}")

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()
        self._access_times.clear()
        logger.info("Cache cleared")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "utilization": f"{len(self._cache) / self.max_size * 100:.1f}%",
        }


class TokenOptimizer:
    """Handles response optimization to reduce token consumption."""

    # Global cache instance
    _cache = ResponseCache(max_size=100, default_ttl=300)

    # Session storage for full responses (enables drill-down without re-fetching)
    _last_responses: Dict[str, Any] = {}
    _last_response_id: str = None

    # Default limits for different endpoint types
    DEFAULT_LIMITS = {
        "list": 10,
        "get_all": 20,
        "services": 25,
        "servers": 25,
        "osds": 30,
        "stats": 50,
        "logs": 100,
        "audit": 50,
        "export": 200,
    }

    # Essential fields for common resources
    ESSENTIAL_FIELDS = {
        "servers": ["id", "hostname", "ip", "status", "role"],
        "services": ["id", "name", "type", "status", "hostname"],
        "osds": ["id", "osd", "status", "host", "used_percent", "up"],
        "pools": ["name", "pool_id", "size", "used_bytes", "percent_used"],
        "rbds": ["name", "pool", "size", "used_size"],
        "s3": ["bucket", "owner", "size", "num_objects"],
        "tasks": ["id", "name", "status", "progress", "error"],
        "logs": ["timestamp", "level", "service", "message"],
    }

    @classmethod
    def should_optimize(cls, url: str, method: str) -> bool:
        """Check if this request should be optimized."""
        # Only optimize GET requests that likely return lists
        if method.upper() != "GET":
            return False

        # Check if URL suggests a list operation
        list_indicators = ["/list", "/all", "get_all", "/export"]
        return any(indicator in url.lower() for indicator in list_indicators)

    @classmethod
    def add_default_limit(cls, url: str, params: Dict) -> Dict:
        """Add a default limit parameter if not present."""
        # Don't add if already has pagination params
        if any(key in params for key in ["limit", "max", "size", "offset", "page"]):
            return params

        # Determine appropriate limit based on URL
        limit = cls.DEFAULT_LIMITS.get("list", 25)  # default

        for keyword, specific_limit in cls.DEFAULT_LIMITS.items():
            if keyword in url.lower():
                limit = specific_limit
                break

        params["limit"] = limit
        logger.info(f"Auto-added limit={limit} for {url}")
        return params

    @classmethod
    def truncate_response(cls, data: Any, url: str, max_items: int = 50) -> Any:
        """
        Truncate large responses with metadata about truncation.

        Args:
            data: The response data
            url: The request URL (to determine appropriate limits)
            max_items: Maximum items to return

        Returns:
            Truncated data with metadata if applicable
        """
        # Only truncate lists
        if not isinstance(data, list):
            return data

        original_count = len(data)
        if original_count <= max_items:
            return data

        # Adjust limit based on data type
        if "/log" in url.lower() or "/audit" in url.lower():
            max_items = min(100, original_count)  # More for logs
        elif "/stats" in url.lower():
            max_items = min(75, original_count)  # Medium for stats
        elif any(
            resource in url.lower() for resource in ["/services", "/servers", "/osds"]
        ):
            max_items = min(25, original_count)  # Less for resources

        truncated_data = data[:max_items]

        logger.warning(f"Truncated response from {original_count} to {max_items} items")

        return {
            "data": truncated_data,
            "_truncation_metadata": {
                "truncated": True,
                "original_count": original_count,
                "returned_count": max_items,
                "truncation_message": (
                    f"Response truncated from {original_count} to {max_items} items to save tokens. "
                    f"Use pagination (limit/offset) or filters to get specific data."
                ),
            },
        }

    @classmethod
    def filter_fields(cls, data: Any, resource_type: str) -> Any:
        """
        Filter response to only essential fields.

        Args:
            data: The response data
            resource_type: Type of resource (servers, services, etc.)

        Returns:
            Data with only essential fields
        """
        essential = cls.ESSENTIAL_FIELDS.get(resource_type)
        if not essential:
            return data

        if isinstance(data, list):
            return [cls._filter_object_fields(item, essential) for item in data]
        elif isinstance(data, dict):
            return cls._filter_object_fields(data, essential)

        return data

    @classmethod
    def _filter_object_fields(cls, obj: Dict, fields: List[str]) -> Dict:
        """Filter a single object to only include specified fields."""
        if not isinstance(obj, dict):
            return obj

        return {key: obj[key] for key in fields if key in obj}

    @classmethod
    def generate_summary(cls, data: Any, summary_type: str = "stats") -> Dict:
        """
        Generate a summary of large datasets instead of full data.

        Args:
            data: The response data
            summary_type: Type of summary (stats, count, errors_only, etc.)

        Returns:
            Summary dictionary
        """
        if not isinstance(data, list):
            return {"error": "Summary only available for list responses"}

        summary = {
            "total_count": len(data),
            "summary_type": summary_type,
        }

        if summary_type == "count":
            # Just count
            return summary

        elif summary_type == "stats" and data and isinstance(data[0], dict):
            # Statistical summary
            summary["sample"] = data[:3]  # First 3 as sample

            # Count by status if available
            if "status" in data[0]:
                status_counts = {}
                for item in data:
                    status = item.get("status", "unknown")
                    status_counts[status] = status_counts.get(status, 0) + 1
                summary["status_distribution"] = status_counts

            # Count by type if available
            if "type" in data[0]:
                type_counts = {}
                for item in data:
                    item_type = item.get("type", "unknown")
                    type_counts[item_type] = type_counts.get(item_type, 0) + 1
                summary["type_distribution"] = type_counts

        elif summary_type == "errors_only":
            # Only return items with errors
            error_items = [
                item
                for item in data
                if isinstance(item, dict)
                and (
                    item.get("status") in ["error", "failed", "down"]
                    or item.get("error")
                    or item.get("has_error")
                )
            ]
            summary["error_count"] = len(error_items)
            summary["errors"] = error_items[:10]  # Max 10 errors

        return summary

    @classmethod
    def apply_filters(cls, data: Any, filters: Dict[str, Any]) -> Any:
        """
        Apply grep-like filters to response data.

        Supported filter types:
        - Simple equality: {"status": "error"}
        - Multiple values: {"status": ["error", "warning"]}
        - Regex pattern: {"name": "~ceph.*"}
        - Numeric comparison: {"size": ">1000", "cpu": "<=80"}
        - Text search: {"_text": "error"} (searches all string fields)
        - Field existence: {"_has": "error_message"}

        Args:
            data: Response data (list or dict)
            filters: Filter criteria

        Returns:
            Filtered data
        """
        if not filters or not data:
            return data

        # Convert single object to list for uniform processing
        is_single = not isinstance(data, list)
        items = [data] if is_single else data

        filtered = []
        for item in items:
            if not isinstance(item, dict):
                continue

            if cls._item_matches_filters(item, filters):
                filtered.append(item)

        # Log filter effectiveness
        if isinstance(data, list):
            logger.info(f"Filtered from {len(data)} to {len(filtered)} items")

        return filtered[0] if is_single and filtered else filtered

    @classmethod
    def _item_matches_filters(cls, item: Dict, filters: Dict) -> bool:
        """Check if a single item matches all filter criteria."""
        for key, value in filters.items():
            # Special filter: text search across all fields
            if key == "_text":
                if not cls._text_search_in_item(item, value):
                    return False
                continue

            # Special filter: field existence
            if key == "_has":
                fields = value if isinstance(value, list) else [value]
                if not all(field in item for field in fields):
                    return False
                continue

            # Regular field filtering
            if key not in item:
                return False

            item_value = item[key]

            # Regex pattern matching (starts with ~)
            if isinstance(value, str) and value.startswith("~"):
                pattern = value[1:]  # Remove ~ prefix
                try:
                    if not re.search(pattern, str(item_value), re.IGNORECASE):
                        return False
                except re.error:
                    logger.warning(f"Invalid regex pattern: {pattern}")
                    return False

            # Numeric comparisons
            elif isinstance(value, str) and any(
                op in value[:2] for op in [">=", "<=", "!=", ">", "<", "="]
            ):
                if not cls._numeric_comparison(item_value, value):
                    return False

            # Multiple allowed values (OR logic)
            elif isinstance(value, list):
                if item_value not in value:
                    return False

            # Simple equality
            else:
                if item_value != value:
                    return False

        return True

    @classmethod
    def _text_search_in_item(cls, item: Dict, search_text: str) -> bool:
        """Search for text in all string fields of an item."""
        search_lower = search_text.lower()

        def search_in_value(value):
            if isinstance(value, str):
                return search_lower in value.lower()
            elif isinstance(value, dict):
                return any(search_in_value(v) for v in value.values())
            elif isinstance(value, list):
                return any(search_in_value(v) for v in value)
            return False

        return any(search_in_value(v) for v in item.values())

    @classmethod
    def _numeric_comparison(cls, value: Any, comparison: str) -> bool:
        """Perform numeric comparison like '>100' or '<=50'."""
        try:
            # Extract operator and number
            if comparison.startswith(">="):
                op, num = ">=", float(comparison[2:])
                return float(value) >= num
            elif comparison.startswith("<="):
                op, num = "<=", float(comparison[2:])
                return float(value) <= num
            elif comparison.startswith("!="):
                op, num = "!=", float(comparison[2:])
                return float(value) != num
            elif comparison.startswith(">"):
                op, num = ">", float(comparison[1:])
                return float(value) > num
            elif comparison.startswith("<"):
                op, num = "<", float(comparison[1:])
                return float(value) < num
            elif comparison.startswith("="):
                op, num = "=", float(comparison[1:])
                return float(value) == num
            else:
                # Try direct numeric comparison
                return float(value) == float(comparison)
        except (ValueError, TypeError):
            return False

    @classmethod
    def add_optimization_hints(cls, tool_description: str, endpoint_path: str) -> str:
        """
        Add token optimization hints to tool descriptions.

        Args:
            tool_description: Original tool description
            endpoint_path: The API endpoint path

        Returns:
            Enhanced description with optimization hints
        """
        # Check if this endpoint typically returns large data
        large_data_patterns = ["/list", "/all", "/export", "/stats", "/logs"]
        is_large = any(
            pattern in endpoint_path.lower() for pattern in large_data_patterns
        )

        if not is_large:
            return tool_description

        hints = """

💡 Token Optimization Tips:
• Use 'limit=10' for initial exploration
• Add filters to narrow results (e.g., status='error')
• Request specific fields if supported
• For counts only, check if a summary endpoint exists
• Consider pagination for large datasets (offset/limit)
• Results are cached for 5-15 minutes to save tokens
"""

        # Add specific hints based on endpoint type
        if "/services" in endpoint_path:
            hints += "• Filter by service type or status for relevant results\n"
        elif "/servers" in endpoint_path:
            hints += "• Filter by server role or status\n"
        elif "/logs" in endpoint_path:
            hints += "• Use time ranges and severity filters\n"
        elif "/stats" in endpoint_path:
            hints += "• Consider using aggregation parameters if available\n"

        return tool_description + hints

    @classmethod
    def apply_smart_prefilter(cls, url: str, params: Dict) -> tuple[str, Dict]:
        """
        Apply smart pre-filtering to reduce API response size before request.

        Args:
            url: The API endpoint URL
            params: Original request parameters

        Returns:
            Tuple of (modified_url, modified_params)
        """
        if not params:
            return url, params

        # Extract filter parameters
        filters = {}
        modified_params = params.copy()

        # Check for common filter patterns
        if "_filter_status" in params:
            filters["status"] = params["_filter_status"]
            del modified_params["_filter_status"]

        if "_filter_name" in params:
            name_filter = params["_filter_name"]
            if name_filter.startswith("~"):
                # Regex filter - convert to API-specific format if supported
                filters["name"] = name_filter[1:]  # Remove ~ prefix
            else:
                filters["name"] = name_filter
            del modified_params["_filter_name"]

        # Apply filters to URL if the endpoint supports it
        if filters and any(pattern in url.lower() for pattern in ["/list", "/all"]):
            # Convert filters to query parameters
            filter_params = []
            for key, value in filters.items():
                if isinstance(value, list):
                    filter_params.extend([f"{key}={v}" for v in value])
                else:
                    filter_params.append(f"{key}={value}")

            if filter_params:
                separator = "&" if "?" in url else "?"
                url = f"{url}{separator}" + "&".join(filter_params)
                logger.info(f"Applied pre-filters: {filter_params}")

        return url, modified_params

    @classmethod
    def analyze_query_context(cls, query: str) -> Dict[str, Any]:
        """
        Analyze LLM query to determine optimization strategy.

        Args:
            query: The LLM's query string

        Returns:
            Dictionary with optimization recommendations
        """
        query_lower = query.lower()

        recommendations = {
            "count_only": False,
            "error_only": False,
            "status_check": False,
            "exploration": False,
            "detailed_analysis": False,
            "suggested_limit": None,
            "suggested_filters": [],
        }

        # Detect count queries
        if any(
            word in query_lower for word in ["how many", "count", "number of", "total"]
        ):
            recommendations["count_only"] = True
            recommendations["suggested_limit"] = 0  # Only return count

        # Detect error-focused queries
        if any(
            word in query_lower
            for word in ["error", "problem", "issue", "failed", "down"]
        ):
            recommendations["error_only"] = True
            recommendations["suggested_filters"].append("status:error")

        # Detect status queries
        if any(
            word in query_lower for word in ["status", "health", "state", "running"]
        ):
            recommendations["status_check"] = True
            recommendations["suggested_limit"] = 20

        # Detect exploration queries
        if any(word in query_lower for word in ["list", "show", "get", "display"]):
            recommendations["exploration"] = True
            recommendations["suggested_limit"] = 10

        # Detect detailed analysis queries
        if any(
            word in query_lower
            for word in ["analyze", "detailed", "full", "complete", "all"]
        ):
            recommendations["detailed_analysis"] = True
            recommendations["suggested_limit"] = 50

        return recommendations

    @classmethod
    def optimize_for_context(cls, data: Any, context: Dict[str, Any]) -> Any:
        """
        Optimize response based on query context analysis.

        Args:
            data: The API response data
            context: Optimization context from analyze_query_context

        Returns:
            Optimized response data
        """
        if not isinstance(data, list):
            return data

        if context.get("count_only"):
            return {"count": len(data)}

        if context.get("error_only"):
            errors = [
                item
                for item in data
                if isinstance(item, dict)
                and item.get("status") in ["error", "failed", "down"]
            ]
            return {
                "error_count": len(errors),
                "errors": errors[:10],  # Max 10 errors
                "total_count": len(data),
            }

        if context.get("status_check"):
            # Group by status for status queries
            status_groups = {}
            for item in data:
                if isinstance(item, dict):
                    status = item.get("status", "unknown")
                    status_groups[status] = status_groups.get(status, 0) + 1

            return {
                "status_summary": status_groups,
                "total_count": len(data),
                "sample": data[:3],  # Small sample
            }

        # Apply suggested limit
        suggested_limit = context.get("suggested_limit")
        if suggested_limit is not None and len(data) > suggested_limit:
            return {
                "data": data[:suggested_limit],
                "_context_optimization": {
                    "original_count": len(data),
                    "returned_count": suggested_limit,
                    "query_type": context.get("exploration")
                    and "exploration"
                    or "specific",
                    "message": f"Response optimized for {context.get('exploration', 'specific')} query. Use pagination for more data.",
                },
            }

        return data

    @classmethod
    def add_progressive_loading(
        cls, data: Any, url: str, limit: int = 25
    ) -> Dict[str, Any]:
        """
        Add progressive loading metadata for large datasets.

        Args:
            data: The API response data
            url: The endpoint URL
            limit: Current limit applied

        Returns:
            Data with progressive loading metadata
        """
        if not isinstance(data, list):
            return data

        has_more = len(data) == limit
        next_cursor = None

        if has_more and data:
            # Generate cursor from last item's ID or timestamp
            last_item = data[-1]
            if isinstance(last_item, dict):
                if "id" in last_item:
                    next_cursor = str(last_item["id"])
                elif "timestamp" in last_item:
                    next_cursor = str(last_item["timestamp"])
                elif "name" in last_item:
                    next_cursor = str(last_item["name"])

        return {
            "data": data,
            "_progressive": {
                "has_more": has_more,
                "next_cursor": next_cursor,
                "current_limit": limit,
                "returned_count": len(data),
                "message": (
                    "Use next_cursor with limit parameter for progressive loading"
                    if has_more
                    else "All data loaded"
                ),
            },
        }

    @classmethod
    def compress_large_response(
        cls, data: Any, threshold: int = 10240
    ) -> Dict[str, Any]:
        """
        Compress very large responses to save tokens.

        Args:
            data: The response data to potentially compress
            threshold: Size threshold in bytes (default: 10KB)

        Returns:
            Data with compression metadata if compression was applied
        """
        # Only compress list data
        if not isinstance(data, list):
            return data

        # Calculate response size
        json_str = json.dumps(data, separators=(",", ":"))
        size_bytes = len(json_str.encode("utf-8"))

        if size_bytes <= threshold:
            return data

        try:
            # Compress the data
            compressed_bytes = gzip.compress(json_str.encode("utf-8"))
            compressed_b64 = base64.b64encode(compressed_bytes).decode("ascii")

            compression_ratio = len(compressed_b64) / size_bytes
            savings = 1 - compression_ratio

            logger.info(
                f"Compressed response from {size_bytes} to {len(compressed_b64)} bytes ({savings:.1%} savings)"
            )

            return {
                "_compressed": True,
                "data": compressed_b64,
                "compression_info": {
                    "original_size": size_bytes,
                    "compressed_size": len(compressed_b64),
                    "compression_ratio": f"{compression_ratio:.3f}",
                    "space_saved": f"{savings:.1%}",
                    "decompression_note": "Data is gzip-compressed and base64-encoded. Use standard gzip + base64 decoding.",
                },
                "original_format": "application/json",
                "compression_method": "gzip+base64",
            }

        except (TypeError, ValueError) as e:
            # Data serialization errors (can't convert to JSON or bytes)
            logger.warning(f"Compression failed - serialization error: {e}")
            return data
        except (OSError, IOError) as e:
            # Compression I/O errors
            logger.warning(f"Compression failed - I/O error: {e}")
            return data

    @classmethod
    def project_fields(cls, data: Any, fields: List[str]) -> Any:
        """
        Project only specified fields from response data (field selection/projection).

        This is the MOST EFFECTIVE token optimization - returns only requested fields.

        Args:
            data: Response data (list of objects or single object)
            fields: List of field names to include

        Returns:
            Data with only the specified fields
        """
        if not fields:
            return data

        def project_object(obj: Dict) -> Dict:
            """Project fields from a single object"""
            if not isinstance(obj, dict):
                return obj
            return {field: obj.get(field) for field in fields if field in obj}

        # Handle list responses
        if isinstance(data, list):
            return [project_object(item) for item in data]

        # Handle single object
        elif isinstance(data, dict):
            # Check if it's a wrapper with 'data' field
            if "data" in data and isinstance(data["data"], list):
                return {
                    **data,
                    "data": [project_object(item) for item in data["data"]],
                    "_field_projection": f"Projected to {len(fields)} fields: {', '.join(fields)}",
                }
            else:
                # Direct object
                return project_object(data)

        return data

    @classmethod
    def create_smart_summary(
        cls, data: Any, url: str, response_id: str = None
    ) -> Dict[str, Any]:
        """
        Create an intelligent summary that preserves critical info while drastically reducing tokens.

        Returns a summary with:
        - Total count
        - Status/error breakdown
        - Critical items (errors, warnings)
        - Reference to drill down for more details

        Args:
            data: The full response data
            url: The endpoint URL (for context)
            response_id: Unique ID to reference this response later

        Returns:
            Smart summary dictionary
        """
        import hashlib
        import time

        # Generate response ID if not provided
        if not response_id:
            response_id = hashlib.md5(f"{url}:{time.time()}".encode()).hexdigest()[:8]

        # Store full response for later drill-down
        cls._last_responses[response_id] = data
        cls._last_response_id = response_id

        # Handle non-list data
        if not isinstance(data, list):
            if isinstance(data, dict):
                # Single object - check for error indicators
                has_error = any(
                    key in data for key in ["error", "errors", "failed", "status"]
                )
                if has_error:
                    return {
                        "_summary": "Single object response (error detected)",
                        "_response_id": response_id,
                        "data": data,  # Include full data for errors
                        "_hint": "This is the complete response (single object with error)",
                    }
                else:
                    return {
                        "_summary": "Single object response",
                        "_response_id": response_id,
                        "data": data,
                        "_hint": "This is the complete response (single object)",
                    }
            else:
                # Primitive value
                return data

        # List data - create intelligent summary
        total_count = len(data)

        # Quick return for small lists
        if total_count <= 5:
            return {
                "_summary": f"Small dataset ({total_count} items) - showing all",
                "_response_id": response_id,
                "items": data,
                "_hint": "Complete data shown (≤5 items)",
            }

        summary = {
            "_summary": f"Found {total_count} items",
            "_response_id": response_id,
            "total_count": total_count,
        }

        # Analyze first item to understand structure
        if data and isinstance(data[0], dict):
            first_item = data[0]

            # Count by status
            if "status" in first_item:
                status_counts = {}
                critical_statuses = []
                for item in data:
                    status = item.get("status", "unknown")
                    status_counts[status] = status_counts.get(status, 0) + 1
                    if status in ["error", "failed", "down", "critical"]:
                        critical_statuses.append(item)

                summary["by_status"] = status_counts
                if critical_statuses:
                    summary["critical_items"] = critical_statuses[:5]
                    summary["critical_count"] = len(critical_statuses)

            # Detect errors
            error_items = []
            for item in data:
                if isinstance(item, dict):
                    has_error = (
                        item.get("status") in ["error", "failed", "down"]
                        or item.get("error")
                        or item.get("has_error")
                        or item.get("health") == "ERROR"
                    )
                    if has_error:
                        error_items.append(item)

            if error_items:
                summary["errors_found"] = len(error_items)
                summary["error_samples"] = error_items[:3]

            # Sample items
            summary["sample_items"] = data[:3]

            # Available fields
            all_keys = set()
            for item in data[:10]:  # Check first 10 items
                if isinstance(item, dict):
                    all_keys.update(item.keys())
            summary["available_fields"] = sorted(list(all_keys))

        else:
            # List of primitives
            summary["sample_items"] = data[:5]

        # Add drill-down hint
        summary["_hint"] = (
            f"💡 This is a summary of {total_count} items. "
            f"Use search_last_result(response_id='{response_id}') to filter/search the full data. "
            f"Available filters: field=value, field__contains=text, field__gt=number"
        )

        return summary

    @classmethod
    def search_stored_response(
        cls, response_id: str = None, filters: Dict[str, Any] = None, limit: int = None
    ) -> Dict[str, Any]:
        """
        Search through a previously stored response.

        Args:
            response_id: ID of stored response (uses last if not specified)
            filters: grep-like filters to apply
            limit: Maximum items to return

        Returns:
            Filtered results
        """
        # Get response ID
        if not response_id:
            response_id = cls._last_response_id

        if not response_id or response_id not in cls._last_responses:
            return {
                "error": "No stored response found",
                "hint": "Make an API call first, then use the response_id from the summary",
            }

        data = cls._last_responses[response_id]

        # Apply filters if provided
        if filters:
            data = cls.apply_filters(data, filters)

        # Apply limit
        if limit and isinstance(data, list):
            data = data[:limit]

        return {
            "response_id": response_id,
            "matched_count": len(data) if isinstance(data, list) else 1,
            "results": data,
        }


# Integration functions for the main MCP server
def optimize_api_response(
    url: str,
    method: str,
    response_data: Any,
    params: Dict = None,
    requested_fields: List[str] = None,
) -> Any:
    """
    Main entry point for response optimization.

    Strategy (in order of priority):
    1. Field projection (if requested_fields provided): Only return specified fields
    2. Small responses (≤5 items): Return as-is
    3. Medium responses (6-50 items): Apply truncation
    4. Large responses (>50 items): Create smart summary with drill-down capability

    Args:
        url: The API endpoint URL
        method: HTTP method
        response_data: The raw response data
        params: Query parameters used
        requested_fields: List of field names to include (highest priority optimization)

    Returns:
        Optimized response data (summary or full data)
    """
    # Skip if optimization disabled
    if params and params.get("no_optimize"):
        return response_data

    # Apply field projection FIRST if requested (highest priority - can save 80-95% tokens)
    if requested_fields:
        response_data = TokenOptimizer.project_fields(response_data, requested_fields)
        # Field projection is so effective that we can be less aggressive with size limits
        # Only create summary for VERY large responses (>100 items) when fields are projected
        if isinstance(response_data, list) and len(response_data) > 100:
            return TokenOptimizer.create_smart_summary(response_data, url)
        else:
            # Return projected data as-is (already optimized)
            return response_data

    # Determine response size
    item_count = None
    if isinstance(response_data, list):
        item_count = len(response_data)
    elif isinstance(response_data, dict) and "data" in response_data:
        if isinstance(response_data["data"], list):
            item_count = len(response_data["data"])

    # Small responses - no optimization needed
    if item_count is not None and item_count <= 5:
        return response_data

    # Medium responses - apply truncation
    if item_count is not None and 5 < item_count <= 50:
        return TokenOptimizer.truncate_response(response_data, url, max_items=25)

    # Large responses - create smart summary
    if item_count is not None and item_count > 50:
        return TokenOptimizer.create_smart_summary(response_data, url)

    # Non-list data - return as-is
    return response_data


def get_cached_response(url: str, method: str, params: Dict = None) -> Optional[Any]:
    """
    Get response from cache if available.

    Args:
        url: The API endpoint URL
        method: HTTP method
        params: Query parameters used

    Returns:
        Cached response data or None
    """
    return TokenOptimizer._cache.get(url, method, params)


def cache_response(
    url: str, method: str, data: Any, params: Dict = None, ttl: int = None
) -> None:
    """
    Cache response data.

    Args:
        url: The API endpoint URL
        method: HTTP method
        data: Response data to cache
        params: Query parameters used
        ttl: Custom TTL in seconds
    """
    TokenOptimizer._cache.set(url, method, data, params, ttl)


def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics."""
    return TokenOptimizer._cache.get_stats()


def search_last_result(
    response_id: str = None, filters: Dict[str, Any] = None, limit: int = 100
) -> Dict[str, Any]:
    """
    Search through the last API response for specific items.

    This allows the LLM to drill down into large responses without
    re-fetching data from the API.

    Args:
        response_id: ID from the summary (optional, uses last if not specified)
        filters: Dictionary of filters (e.g., {"status": "error", "name__contains": "osd"})
        limit: Maximum items to return (default: 100)

    Returns:
        Filtered results from the stored response
    """
    return TokenOptimizer.search_stored_response(response_id, filters, limit)
