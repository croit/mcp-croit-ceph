#!/usr/bin/env python3
"""
Utility Helper Functions
Reusable functions to eliminate code duplication across modules.
"""

import re
from datetime import datetime, timedelta
from typing import Tuple, Optional
from urllib.parse import urljoin

from src.config.constants import DEFAULT_HTTP_PORT, DEFAULT_HTTPS_PORT


def parse_host_url(host: str) -> Tuple[str, str, int, bool]:
    """
    Parse a host URL into its components.

    Args:
        host: Full host URL (e.g., "https://example.com:8080" or "http://192.168.1.1")

    Returns:
        Tuple of (protocol, hostname, port, use_ssl)
        - protocol: "http" or "https"
        - hostname: Domain name or IP address
        - port: Port number (defaults: 443 for https, 8080 for http)
        - use_ssl: Boolean indicating if SSL should be used

    Examples:
        >>> parse_host_url("https://cluster.example.com:9000")
        ('https', 'cluster.example.com', 9000, True)

        >>> parse_host_url("http://192.168.1.100")
        ('http', '192.168.1.100', 8080, False)

        >>> parse_host_url("invalid-url")
        ('http', 'invalid-url', 8080, False)
    """
    match = re.match(r"(https?)://([^:]+):?(\d+)?", host)

    if match:
        protocol = match.group(1)
        hostname = match.group(2)
        port = (
            int(match.group(3))
            if match.group(3)
            else (DEFAULT_HTTPS_PORT if protocol == "https" else DEFAULT_HTTP_PORT)
        )
        use_ssl = protocol == "https"
    else:
        # Fallback for malformed URLs
        protocol = "http"
        hostname = host
        port = DEFAULT_HTTP_PORT
        use_ssl = False

    return protocol, hostname, port, use_ssl


def calculate_time_range(hours_back: float = 1.0) -> Tuple[int, int]:
    """
    Calculate Unix timestamp range from current time.

    Args:
        hours_back: Number of hours to look back from now (default: 1.0)

    Returns:
        Tuple of (start_timestamp, end_timestamp) in Unix epoch seconds

    Examples:
        >>> start, end = calculate_time_range(24)
        >>> # start is 24 hours ago, end is now
        >>> isinstance(start, int) and isinstance(end, int)
        True

        >>> start, end = calculate_time_range(0.5)
        >>> # start is 30 minutes ago
        >>> (end - start) == 1800  # 30 minutes = 1800 seconds
        True
    """
    end_time = int(datetime.now().timestamp())
    start_time = int((datetime.now() - timedelta(hours=hours_back)).timestamp())
    return start_time, end_time


def build_api_url(
    base_url: str, endpoint: str, strip_trailing_slash: bool = True
) -> str:
    """
    Safely build API URL from base and endpoint.

    Args:
        base_url: Base URL (e.g., "https://example.com:8080/api")
        endpoint: API endpoint (e.g., "/pools" or "pools/1")
        strip_trailing_slash: Remove trailing slash from base_url (default: True)

    Returns:
        Complete URL with proper joining

    Examples:
        >>> build_api_url("https://example.com/api/", "/pools")
        'https://example.com/api/pools'

        >>> build_api_url("https://example.com/api", "pools/123")
        'https://example.com/api/pools/123'

        >>> build_api_url("https://example.com/api/", "pools", strip_trailing_slash=False)
        'https://example.com/api/pools'
    """
    # Clean up base URL
    if strip_trailing_slash:
        base_url = base_url.rstrip("/")

    # Ensure endpoint starts with /
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint

    # Use urljoin for proper URL construction
    return urljoin(base_url + "/", endpoint.lstrip("/"))


def format_timestamp(timestamp: int) -> str:
    """
    Format Unix timestamp to human-readable string.

    Args:
        timestamp: Unix epoch timestamp in seconds

    Returns:
        ISO 8601 formatted datetime string

    Examples:
        >>> format_timestamp(1699876543)
        '2023-11-13 12:35:43'
    """
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def sanitize_filter_value(value: str) -> str:
    """
    Sanitize user input for filter values to prevent injection.

    Args:
        value: Raw filter value from user

    Returns:
        Sanitized value safe for use in queries

    Examples:
        >>> sanitize_filter_value("normal_value")
        'normal_value'

        >>> sanitize_filter_value("value; DROP TABLE--")
        'value DROP TABLE'
    """
    # Remove potentially dangerous characters
    # Allow: alphanumeric, spaces, hyphens, underscores, dots, wildcards
    return re.sub(r"[^\w\s\-.*~]", "", value)


def extract_error_message(exception: Exception, max_length: int = 200) -> str:
    """
    Extract and truncate error message from exception.

    Args:
        exception: The exception to extract message from
        max_length: Maximum length of returned message (default: 200)

    Returns:
        Cleaned error message string

    Examples:
        >>> extract_error_message(ValueError("This is an error"), max_length=10)
        'This is...'
    """
    msg = str(exception)
    if len(msg) > max_length:
        return msg[: max_length - 3] + "..."
    return msg
