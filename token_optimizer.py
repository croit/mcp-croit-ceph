#!/usr/bin/env python3
"""
Token optimization module for MCP Croit Ceph.
Provides utilities to reduce token consumption when dealing with large API responses.
"""

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TokenOptimizer:
    """Handles response optimization to reduce token consumption."""

    # Default limits for different endpoint types
    DEFAULT_LIMITS = {
        'list': 10,
        'get_all': 20,
        'services': 25,
        'servers': 25,
        'osds': 30,
        'stats': 50,
        'logs': 100,
        'audit': 50,
        'export': 200,
    }

    # Essential fields for common resources
    ESSENTIAL_FIELDS = {
        'servers': ['id', 'hostname', 'ip', 'status', 'role'],
        'services': ['id', 'name', 'type', 'status', 'hostname'],
        'osds': ['id', 'osd', 'status', 'host', 'used_percent', 'up'],
        'pools': ['name', 'pool_id', 'size', 'used_bytes', 'percent_used'],
        'rbds': ['name', 'pool', 'size', 'used_size'],
        's3': ['bucket', 'owner', 'size', 'num_objects'],
        'tasks': ['id', 'name', 'status', 'progress', 'error'],
        'logs': ['timestamp', 'level', 'service', 'message'],
    }

    @classmethod
    def should_optimize(cls, url: str, method: str) -> bool:
        """Check if this request should be optimized."""
        # Only optimize GET requests that likely return lists
        if method.upper() != 'GET':
            return False

        # Check if URL suggests a list operation
        list_indicators = ['/list', '/all', 'get_all', '/export']
        return any(indicator in url.lower() for indicator in list_indicators)

    @classmethod
    def add_default_limit(cls, url: str, params: Dict) -> Dict:
        """Add a default limit parameter if not present."""
        # Don't add if already has pagination params
        if any(key in params for key in ['limit', 'max', 'size', 'offset', 'page']):
            return params

        # Determine appropriate limit based on URL
        limit = cls.DEFAULT_LIMITS.get('list', 25)  # default

        for keyword, specific_limit in cls.DEFAULT_LIMITS.items():
            if keyword in url.lower():
                limit = specific_limit
                break

        params['limit'] = limit
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
        if '/log' in url.lower() or '/audit' in url.lower():
            max_items = min(100, original_count)  # More for logs
        elif '/stats' in url.lower():
            max_items = min(75, original_count)  # Medium for stats
        elif any(resource in url.lower() for resource in ['/services', '/servers', '/osds']):
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
                )
            }
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
    def generate_summary(cls, data: Any, summary_type: str = 'stats') -> Dict:
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

        if summary_type == 'count':
            # Just count
            return summary

        elif summary_type == 'stats' and data and isinstance(data[0], dict):
            # Statistical summary
            summary["sample"] = data[:3]  # First 3 as sample

            # Count by status if available
            if 'status' in data[0]:
                status_counts = {}
                for item in data:
                    status = item.get('status', 'unknown')
                    status_counts[status] = status_counts.get(status, 0) + 1
                summary["status_distribution"] = status_counts

            # Count by type if available
            if 'type' in data[0]:
                type_counts = {}
                for item in data:
                    item_type = item.get('type', 'unknown')
                    type_counts[item_type] = type_counts.get(item_type, 0) + 1
                summary["type_distribution"] = type_counts

        elif summary_type == 'errors_only':
            # Only return items with errors
            error_items = [
                item for item in data
                if isinstance(item, dict) and (
                    item.get('status') in ['error', 'failed', 'down'] or
                    item.get('error') or
                    item.get('has_error')
                )
            ]
            summary["error_count"] = len(error_items)
            summary["errors"] = error_items[:10]  # Max 10 errors

        return summary

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
        large_data_patterns = ['/list', '/all', '/export', '/stats', '/logs']
        is_large = any(pattern in endpoint_path.lower() for pattern in large_data_patterns)

        if not is_large:
            return tool_description

        hints = """

💡 Token Optimization Tips:
• Use 'limit=10' for initial exploration
• Add filters to narrow results (e.g., status='error')
• Request specific fields if supported
• For counts only, check if a summary endpoint exists
• Consider pagination for large datasets (offset/limit)
"""

        # Add specific hints based on endpoint type
        if '/services' in endpoint_path:
            hints += "• Filter by service type or status for relevant results\n"
        elif '/servers' in endpoint_path:
            hints += "• Filter by server role or status\n"
        elif '/logs' in endpoint_path:
            hints += "• Use time ranges and severity filters\n"
        elif '/stats' in endpoint_path:
            hints += "• Consider using aggregation parameters if available\n"

        return tool_description + hints


# Example integration function for the main MCP server
def optimize_api_response(url: str, method: str, response_data: Any, params: Dict = None) -> Any:
    """
    Main entry point for response optimization.

    Args:
        url: The API endpoint URL
        method: HTTP method
        response_data: The raw response data
        params: Query parameters used

    Returns:
        Optimized response data
    """
    # Skip if optimization disabled
    if params and params.get('no_optimize'):
        return response_data

    # Apply truncation for large responses
    response_data = TokenOptimizer.truncate_response(response_data, url)

    # Could add field filtering here if needed
    # resource_type = extract_resource_type(url)
    # if resource_type:
    #     response_data = TokenOptimizer.filter_fields(response_data, resource_type)

    return response_data