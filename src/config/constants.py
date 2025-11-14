"""
Configuration constants for the MCP Croit Ceph server.

This module centralizes all magic numbers and configuration values
to make them easy to find, understand, and modify.
"""

# =============================================================================
# Schema Resolution
# =============================================================================

# Maximum depth for recursive schema reference resolution
# Prevents infinite loops in circular references
MAX_SCHEMA_RESOLUTION_DEPTH = 10

# Maximum depth for recursive schema property extraction
MAX_SCHEMA_PROPERTY_DEPTH = 5


# =============================================================================
# Cache Settings
# =============================================================================

# Default cache TTL for general API responses (seconds)
DEFAULT_CACHE_TTL_SECONDS = 300  # 5 minutes

# Cache TTL for status/health endpoints (seconds)
STATUS_CACHE_TTL_SECONDS = 60  # 1 minute

# Cache TTL for stats/metrics endpoints (seconds)
STATS_CACHE_TTL_SECONDS = 180  # 3 minutes

# Cache TTL for list/all endpoints (seconds)
LIST_CACHE_TTL_SECONDS = 600  # 10 minutes

# Maximum number of cached responses
MAX_CACHE_SIZE = 100

# Log search cache TTL (seconds)
LOG_SEARCH_CACHE_TTL_SECONDS = 300  # 5 minutes


# =============================================================================
# Token Optimization
# =============================================================================

# Small responses: return as-is without optimization
SMALL_RESPONSE_THRESHOLD = 5

# Medium responses: apply truncation
MEDIUM_RESPONSE_THRESHOLD = 50

# Truncate medium responses to this many items
TRUNCATE_TO_ITEMS = 25

# Large responses: create smart summary (threshold)
LARGE_RESPONSE_SUMMARY_THRESHOLD = 50

# With field projection, only summarize if exceeding this threshold
FIELD_PROJECTION_SUMMARY_THRESHOLD = 100

# Default maximum items in truncated responses
DEFAULT_MAX_ITEMS = 50

# Maximum sample items to show in summaries
MAX_SAMPLE_ITEMS = 3

# Maximum error items to show in summaries
MAX_ERROR_SAMPLES = 5

# Maximum critical events to show in summaries
MAX_CRITICAL_EVENTS = 5


# =============================================================================
# WebSocket & Network
# =============================================================================

# Default network ports
DEFAULT_HTTP_PORT = 8080
DEFAULT_HTTPS_PORT = 443

# WebSocket connection timeout (seconds)
WEBSOCKET_TIMEOUT_SECONDS = 30

# WebSocket message wait timeout (seconds)
WEBSOCKET_MESSAGE_TIMEOUT_SECONDS = 5

# Default API request timeout (seconds)
API_REQUEST_TIMEOUT_SECONDS = 30


# =============================================================================
# Pagination & Limits
# =============================================================================

# Default limit for list operations
DEFAULT_LIST_LIMIT = 10

# Default limit for search operations
DEFAULT_SEARCH_LIMIT = 25

# Default limit for stats/summary operations
DEFAULT_STATS_LIMIT = 100

# Maximum limit for any operation (safety limit)
MAX_LIMIT = 1000


# =============================================================================
# Tool Generation
# =============================================================================

# Maximum number of category-specific tools to generate
MAX_CATEGORY_TOOLS = 10

# Maximum endpoints to show in list_endpoints response
MAX_ENDPOINTS_IN_RESPONSE = 100


# =============================================================================
# Log Search
# =============================================================================

# Default hours to search back in logs
DEFAULT_LOG_HOURS_BACK = 24

# Maximum hours to search back in logs
MAX_LOG_HOURS_BACK = 168  # 1 week

# Default log search limit
DEFAULT_LOG_LIMIT = 1000

# Maximum log entries to return
MAX_LOG_ENTRIES = 10000

# Log entries for large sample analysis (transport, server detection)
LOG_ANALYSIS_SAMPLE_SIZE = 10000

# Log entries for medium sample analysis
LOG_MEDIUM_SAMPLE_SIZE = 2000

# Server discovery lookback hours
SERVER_DISCOVERY_HOURS = 24


# =============================================================================
# Response Compression
# =============================================================================

# Minimum size (bytes) before applying compression
COMPRESSION_THRESHOLD_BYTES = 10240  # 10 KB

# Maximum message length in log summaries (characters)
MAX_LOG_MESSAGE_LENGTH = 200


# =============================================================================
# Field Selection
# =============================================================================

# Essential fields to suggest for most endpoints
ESSENTIAL_FIELDS = ["id", "name", "status"]

# Maximum fields to show in field hints
MAX_FIELDS_IN_HINT = 8
