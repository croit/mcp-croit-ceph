#!/usr/bin/env python3
"""
MCP Croit Ceph Extension
Dynamically loads swagger.json from croit.io host and generates tools
"""

from dataclasses import dataclass
import os
import json
import argparse
import asyncio
import logging
import requests
from typing import Any, Dict, List, Optional
from pathlib import Path
import aiohttp
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.server.stdio
import mcp.types as types

logging.basicConfig(
    level=logging.INFO, format="[%(asctime)s] %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Import log search tools
try:
    from croit_log_tools import handle_log_search, handle_log_check, LOG_SEARCH_TOOLS

    LOG_TOOLS_AVAILABLE = True
except ImportError:
    logger.warning("croit_log_tools module not found, log search features disabled")
    LOG_TOOLS_AVAILABLE = False

# Try to import token_optimizer, fall back gracefully if not available
try:
    from token_optimizer import TokenOptimizer

    TOKEN_OPTIMIZER_AVAILABLE = True
except ImportError:
    logger.warning(
        "token_optimizer module not found, filtering and optimization disabled"
    )
    TOKEN_OPTIMIZER_AVAILABLE = False

    # Create a dummy TokenOptimizer class with no-op methods
    class TokenOptimizer:
        @classmethod
        def should_optimize(cls, url, method):
            return False

        @classmethod
        def add_default_limit(cls, url, params):
            return params

        @classmethod
        def truncate_response(cls, data, url):
            return data

        @classmethod
        def apply_filters(cls, data, filters):
            return data


class CroitCephServer:
    def __init__(
        self,
        mode="hybrid",  # Supported modes: "hybrid", "base_only", "categories_only"
        resolve_references=True,
        offer_whole_spec=False,
        max_category_tools=10,  # Maximum number of category tools to generate
        min_endpoints_per_category=1,  # Minimum endpoints needed for a category tool
        openapi_file=None,  # Optional: Use local OpenAPI spec file instead of fetching from server
        use_included_api_spec=False,  # Use OpenAPI spec bundled with the package
        enable_log_tools=True,  # Enable advanced log search tools
        enable_daos=False,  # Enable DAOS-specific tools and endpoints
        enable_specialty_features=True,  # Enable specialty features (rbd-mirror, etc.)
    ):
        # mcp_tools contains the list of tools that will be advertised to the LLM
        self.mcp_tools: List[types.Tool] = []
        # api_spec contains the OpenAPI schema as returned from the cluster
        self.api_spec = None
        # host is the cluster URL, e.g. http://172.31.134.4:8080
        self.host = None
        # resolved_references will be set to true when resolve_references is True
        self.resolved_references = False
        # Category mapping for hybrid and categories_only modes
        self.category_endpoints = {}
        # session is used to make the actual API calls to the cluster
        self.session = aiohttp.ClientSession()
        # Enable log search tools
        self.enable_log_tools = enable_log_tools and LOG_TOOLS_AVAILABLE
        # Feature flags
        self.enable_daos = enable_daos
        self.enable_specialty_features = enable_specialty_features
        # Track if we've shown hints to reduce token usage
        self.hints_shown = False

        # Validate mode
        if mode not in ["hybrid", "base_only", "categories_only"]:
            raise ValueError(
                f"Unsupported mode: {mode}. Use 'hybrid', 'base_only', or 'categories_only'"
            )

        self.mode = mode
        self.max_category_tools = max_category_tools
        self.min_endpoints_per_category = min_endpoints_per_category
        self.openapi_file = openapi_file
        self.packaged_spec_path = Path(__file__).with_name("openapi.json")
        env_use_included = os.environ.get("USE_INCLUDED_API_SPEC", "")
        self.use_included_api_spec = use_included_api_spec or (
            str(env_use_included).lower() in {"1", "true", "yes", "on"}
        )

        if self.use_included_api_spec and not self.openapi_file:
            if self.packaged_spec_path.exists():
                self.openapi_file = str(self.packaged_spec_path)
                logger.info(
                    "USE_INCLUDED_API_SPEC enabled; using bundled spec at %s",
                    self.openapi_file,
                )
            else:
                logger.warning(
                    "USE_INCLUDED_API_SPEC enabled, but bundled spec not found at %s",
                    self.packaged_spec_path,
                )

        self._load_config()
        if self.openapi_file:
            self._load_local_swagger_spec()
        else:
            self._fetch_swagger_spec()

        if resolve_references:
            self._resolve_swagger_references()

        # Store mode for handler use
        self.mode = mode

        # Configure based on mode
        if mode == "hybrid":
            self.offer_whole_spec = offer_whole_spec
            self._analyze_api_structure()
            self._prepare_hybrid_tools()
            tool_handler = self.handle_hybrid_tool
            self.instructions = """This MCP server provides access to a croit Ceph cluster.

Available tools:
- list_endpoints: List API endpoints with filtering options and x-llm-hints
- call_endpoint: Call any API endpoint directly with optimization features
- Category-specific tools with integrated x-llm-hints for common operations

Use category tools for common operations, or use list_endpoints/call_endpoint for any endpoint."""
        elif mode == "categories_only":
            self._analyze_api_structure()
            self._prepare_category_tools_only()
            tool_handler = self.handle_category_tool
            self.instructions = """This MCP server provides access to a croit Ceph cluster.

Category-based tools with integrated x-llm-hints are available for common operations like managing services, pools, and storage."""
        else:  # base_only
            self.offer_whole_spec = offer_whole_spec
            self._prepare_api_tools()
            tool_handler = self.handle_api_call_tool
            self.instructions = """This MCP server provides access to a croit Ceph cluster.
Use list_api_endpoints to get an overview of what endpoints are available.
Use get_reference_schema to get more info on the schema for endpoints.
Use call_api_endpoint to then call one of the endpoints.
Many endpoints offer pagination. When available, use it to refine the query."""

        # Add log search tools if enabled (works in all modes)
        if self.enable_log_tools:
            self._add_log_search_tools()

        self.server = Server("mcp-croit-ceph")

        # Register handlers with proper signatures
        @self.server.list_tools()
        async def list_tools_handler() -> list[types.Tool]:
            return await self.handle_list_tools()

        @self.server.call_tool()
        async def call_tool_handler(
            name: str, arguments: dict
        ) -> list[types.TextContent]:
            try:
                # Call the appropriate handler based on stored mode
                if self.mode == "hybrid":
                    result = await self.handle_hybrid_tool(name, arguments)
                elif self.mode == "categories_only":
                    result = await self.handle_category_tool(name, arguments)
                else:  # base_only
                    result = await self.handle_api_call_tool(name, arguments)

                return [types.TextContent(type="text", text=str(result))]
            except Exception as e:
                raise RuntimeError(str(e))

    def _load_config(self):
        """Load croit API configuration from environment or file, i.e. the target host and the API token."""
        self.host = os.environ.get("CROIT_HOST")
        self.api_token = os.environ.get("CROIT_API_TOKEN")

        # Fallback to config file
        if not self.host or not self.api_token:
            config_path = Path(os.environ.get("CONFIG_PATH", "/config/config.json"))
            if config_path.exists():
                with open(config_path) as f:
                    config = json.load(f)
                    self.host = self.host or config.get("host")
                    self.api_token = self.api_token or config.get("api_token")

        if not self.host or not self.api_token:
            raise RuntimeError("Missing CROIT_HOST or CROIT_API_TOKEN configuration")

        # Ensure host doesn't have trailing slash
        self.host = self.host.rstrip("/")
        self.ssl = self.host.startswith("https")

    def _load_local_swagger_spec(self):
        """Load OpenAPI spec from a local file."""
        logger.info(f"Loading OpenAPI spec from local file: {self.openapi_file}")
        try:
            with open(self.openapi_file, "r") as f:
                self.api_spec = json.load(f)
            logger.info(f"Successfully loaded OpenAPI spec from {self.openapi_file}")
        except FileNotFoundError:
            logger.error(f"OpenAPI spec file not found: {self.openapi_file}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in OpenAPI spec file: {e}")
            raise

    def _fetch_swagger_spec(self):
        """Fetch swagger.json from the croit cluster and store it in self.api_spec."""
        swagger_url = f"{self.host}/api/swagger.json"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
        }

        logger.info(f"Fetching swagger spec from {swagger_url}")
        resp = requests.get(swagger_url, headers=headers, verify=self.ssl)
        if resp.status_code == 200:
            self.api_spec = resp.json()
        else:
            logger.error(f"Failed to fetch swagger spec: {resp.status} - {resp.text()}")

    def _resolve_reference_schema(self, ref_path: str) -> Dict:
        """
        Resolve a $ref reference in the swagger specification.
        E.g. if ref_path is #/components/schemas/ManagedTask, this will return the ManagedTask schema
        as defined in self.api_spec.
        """
        logger.debug(f"Resolving {ref_path}")
        path = ref_path
        if path.startswith("#"):
            path = path[1:]
        keys = path.strip("/").split("/")
        current = self.api_spec
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                raise KeyError(f"Reference {ref_path} not found in specification")
            current = current[key]
        return current

    def _resolve_swagger_references(self):
        """
        Recursively resolve all $ref references in the swagger specification.
        Some LLMs can't deal with $ref, so each $ref gets replaced with its actual definition.
        The drawback is that this will blow up the API spec.
        """

        # To fix the recursion in our PaginationRequest, we let it be a simple string,
        # and instead instruct the LLM to generate JSON encoded in the string.
        pagination_ref = "#/components/schemas/PaginationRequest"
        pagination_schema = {
            "type": "string",
            "description": """
Pagination is JSON encoded in a string.
The JSON (optionally) contains the fields "after", "limit", "where" and "sortBy".
"after" and "limit" are both integers, specifying the offset in the all the data and the limit for this page.
"sortBy" is a list of JSON objects. Each object looks like this: {"column": "...", "order": "ASC"}.
"column" is the field to sort by, "order" is either "ASC" or "DESC".
"where" is also a list of JSON objects. Each object has a oepration as key: {"<operation>": <object>}.
Operations are:
- "_and", <object> then is a list of "where" objects to AND together.
- "_or", <object> then is a list of "where" objects to OR together.
- "_not", <object> then is a single "where" object whose condition is inverted.
- "_search", <object> is a string to do full-text search with.
Alternatively, instead of an operation a where object can look like this: {"<field name>": <field condition object>}.
In this case, a filter will be applied to filter fields based on the given condition.
The field condition object looks like this: {"<filter op>": <filter value>}
Valid filter ops are:
- "_eq", the field value needs to be equal the filter value
- "_neq", not equal
- "_gt", greater than
- "_gte", greater than or equals
- "_lt", less than
- "_lte", less than or equals
- "_regex", matches regex (filter value is a regex)
- "_in", in the filter value as element of a list or substring of a string
- "_nin", not in
- "_contains", field contains the filter value
            """,
        }

        def resolve_references(
            obj,
            root_spec,
            resolved: Dict[str, bool],
        ) -> Optional[Dict]:
            """Helper function for recursion"""
            if isinstance(obj, dict):
                # Check if this dict is a reference
                if "$ref" in obj and len(obj) == 1:
                    # This is a pure reference - resolve it
                    ref_path = obj["$ref"]
                    if ref_path == pagination_ref:
                        return pagination_schema
                    if ref_path in resolved:
                        # The only recursion we really have is with Pagination/WhereCondition.
                        # We already handle that case though.
                        logger.info(f"Recursion for reference {ref_path}, skipping it")
                        return None
                    resolved[ref_path] = True
                    resolved_path = self._resolve_reference_schema(ref_path=ref_path)
                    # Recursively resolve the resolved content too
                    return resolve_references(
                        resolved_path, root_spec, resolved=resolved.copy()
                    )
                else:
                    # Regular dict - resolve all values
                    resolved_paths = {}
                    for key, value in obj.items():
                        resolved_ref = resolve_references(
                            value, root_spec, resolved=resolved.copy()
                        )
                        if resolved_ref is not None:
                            resolved_paths[key] = resolved_ref
                    return resolved_paths
            elif isinstance(obj, list):
                # Resolve all items in the list
                return [
                    resolve_references(item, root_spec, resolved=resolved.copy())
                    for item in obj
                    if item is not None
                ]
            else:
                # Primitive value - return as is
                return obj

        self.api_spec["paths"] = resolve_references(
            self.api_spec.get("paths", {}), self.api_spec, resolved={}
        )
        self.resolved_references = True

    def _convert_openapi_schema_to_json_schema(self, openapi_schema: Dict) -> Dict:
        """
        Convert OpenAPI schema to JSON schema format.
        MCP expects JSON schema. OpenAPI schema is a superset of JSON schema and the MCP schema tends to not fully support JSON schemas,
        so this function is used to make sure MCP can work with the schema.
        """
        # https://spec.openapis.org/oas/v3.1.0.html#schema-object
        # The Schema Object format from OpenAPI is a superset JSON schema.
        # It doesn't add a lot, so we just use it directly and hope it works.
        schema = openapi_schema.get("schema", {}).copy()
        # The description tends to be outside of the OpenAPI schema in a description field.
        if schema.get("description", "") == "":
            schema["description"] = openapi_schema.get("description", "")

        # Recursively resolve $ref references and add examples
        schema = self._resolve_refs_in_schema(schema)

        return schema

    def _resolve_refs_in_schema(
        self, schema: Dict, depth: int = 0, seen_refs: set = None
    ) -> Dict:
        """
        Recursively resolve $ref references in a schema and add inline documentation.
        """
        if depth > 10:  # Prevent infinite recursion
            return schema

        if seen_refs is None:
            seen_refs = set()

        # If this is a $ref, resolve it
        if "$ref" in schema:
            ref = schema["$ref"]
            if ref in seen_refs:
                # Circular reference detected
                return {"type": "object", "description": f"Circular reference to {ref}"}

            seen_refs.add(ref)
            resolved = self._resolve_reference_schema(ref)

            # Keep the original description if present
            if "description" in schema:
                resolved = resolved.copy()
                resolved["description"] = schema["description"]

            # Continue resolving in the resolved schema
            return self._resolve_refs_in_schema(resolved, depth + 1, seen_refs)

        # Process nested schemas
        if "properties" in schema:
            resolved_props = {}
            for prop_name, prop_schema in schema["properties"].items():
                resolved_props[prop_name] = self._resolve_refs_in_schema(
                    prop_schema, depth + 1, seen_refs.copy()
                )
            schema = schema.copy()
            schema["properties"] = resolved_props

        if "items" in schema:
            schema = schema.copy()
            schema["items"] = self._resolve_refs_in_schema(
                schema["items"], depth + 1, seen_refs.copy()
            )

        if "anyOf" in schema:
            schema = schema.copy()
            schema["anyOf"] = [
                self._resolve_refs_in_schema(s, depth + 1, seen_refs.copy())
                for s in schema["anyOf"]
            ]

        if "oneOf" in schema:
            schema = schema.copy()
            schema["oneOf"] = [
                self._resolve_refs_in_schema(s, depth + 1, seen_refs.copy())
                for s in schema["oneOf"]
            ]

        if "allOf" in schema:
            schema = schema.copy()
            schema["allOf"] = [
                self._resolve_refs_in_schema(s, depth + 1, seen_refs.copy())
                for s in schema["allOf"]
            ]

        return schema

    def _analyze_api_structure(self):
        """
        Analyze the OpenAPI spec to categorize endpoints by tags.
        Populates self.category_endpoints with a mapping of categories to their endpoints.
        """
        from collections import Counter

        tag_counter = Counter()
        self.category_endpoints = {}

        paths = self.api_spec.get("paths", {})
        for path, methods in paths.items():
            for method, operation in methods.items():
                if method.lower() not in ["get", "post", "put", "delete", "patch"]:
                    continue

                if operation.get("deprecated", False):
                    continue

                tags = operation.get("tags", [])
                for tag in tags:
                    tag_counter[tag] += 1
                    if tag not in self.category_endpoints:
                        self.category_endpoints[tag] = []

                    endpoint_info = {
                        "path": path,
                        "method": method.lower(),
                        "operationId": operation.get("operationId", ""),
                        "summary": operation.get("summary", ""),
                        "description": operation.get("description", ""),
                        "llm_hints": operation.get("x-llm-hints", {}),
                    }
                    self.category_endpoints[tag].append(endpoint_info)

        # Filter categories based on feature flags
        filtered_tag_counter = {}
        for tag, count in tag_counter.items():
            # Skip DAOS if not enabled
            if tag == "daos" and not self.enable_daos:
                continue
            # Skip specialty features if not enabled
            if not self.enable_specialty_features and tag in [
                "rbd-mirror",
                "qos-settings",
                "ceph-keys",
            ]:
                continue
            filtered_tag_counter[tag] = count

        # Sort categories by operation count and select top categories
        potential_categories = [
            cat
            for cat, count in Counter(filtered_tag_counter).most_common(
                self.max_category_tools * 2
            )  # Get more initially
            if count >= self.min_endpoints_per_category
        ]

        # Test permissions for each category if enabled
        if getattr(self, "check_permissions", True):
            self.top_categories = self._filter_categories_by_permission(
                potential_categories
            )
        else:
            self.top_categories = potential_categories[: self.max_category_tools]

        logger.info(
            f"Found {len(tag_counter)} categories, selected {len(self.top_categories)} accessible: {self.top_categories}"
        )

    def _get_user_roles(self) -> List[str]:
        """
        Get user roles from /auth/token-info endpoint.
        Returns list of roles. Raises exception if token is invalid.
        """
        import requests

        try:
            token_info_url = f"{self.host}/api/auth/token-info"
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Accept": "application/json",
            }

            resp = requests.get(
                token_info_url, headers=headers, verify=self.ssl, timeout=5
            )

            if resp.status_code == 200:
                data = resp.json()
                roles = data.get("roles", [])
                logger.info(f"User roles detected: {roles}")
                return (
                    roles if roles else ["VIEWER"]
                )  # Default to VIEWER if empty (shouldn't happen)
            elif resp.status_code == 401:
                logger.error("Invalid API token - authentication failed")
                raise RuntimeError(
                    "Invalid API token. Please check your CROIT_API_TOKEN."
                )
            else:
                logger.error(f"Unexpected response from token-info: {resp.status_code}")
                raise RuntimeError(
                    f"Failed to verify API token: HTTP {resp.status_code}"
                )

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to connect to Croit API: {e}")
            raise RuntimeError(f"Cannot connect to Croit API at {self.host}: {e}")

    def _filter_categories_by_permission(self, categories: List[str]) -> List[str]:
        """
        Filter categories based on user roles.
        Returns only categories where the user has access based on their role.
        Every valid API token has a role, so this should always work.
        """
        # Get user roles (will raise exception if token is invalid)
        user_roles = self._get_user_roles()

        # Check if user has admin role (full access)
        has_admin = "ADMIN" in user_roles or "ADMINISTRATOR" in user_roles

        if has_admin:
            logger.info("User has ADMIN role - all categories accessible")
            return categories[: self.max_category_tools]

        # Categories that require ADMIN role for write operations
        admin_only_categories = {
            "maintenance",  # System maintenance operations
            "servers",  # Server management
            "ipmi",  # IPMI/hardware control
            "config",  # Configuration changes
            "hooks",  # System hooks
            "change-requests",  # Change management
            "config-templates",  # Configuration templates
        }

        # For VIEWER/READ_ONLY users, filter out admin-only categories
        logger.info(f"User has roles {user_roles} - filtering categories")

        accessible_categories = []
        for category in categories:
            # Skip admin-only categories for non-admin users
            if category in admin_only_categories:
                logger.debug(f"Category '{category}' requires ADMIN role - skipping")
                continue

            # All other categories are accessible for read operations
            accessible_categories.append(category)
            logger.debug(f"Category '{category}' accessible for role {user_roles}")

            # Stop when we have enough categories
            if len(accessible_categories) >= self.max_category_tools:
                break

        return accessible_categories

    def _prepare_hybrid_tools(self):
        """
        Prepare hybrid tools: base tools + category tools for top categories.
        """
        # Base tools
        self.list_endpoints_tool = "list_endpoints"
        self.call_endpoint_tool = "call_endpoint"
        self.get_schema_tool = "get_schema"

        # Base tool: list_endpoints with filtering and hints
        list_endpoints_desc = """List available API endpoints with smart filtering and prioritization.

Token Optimization & Smart Search:
• Returns endpoint metadata including x-llm-hints
• Automatically prioritizes most relevant endpoints (e.g., Ceph pools over DAOS pools)
• Filter by category to reduce response size
• Smart truncation shows priority results first

Intent-based filtering:
• intent="read" - Only GET operations (status, list, details)
• intent="write" - Only POST/PUT/PATCH operations (create, update)
• intent="manage" - Only DELETE operations (remove, destroy)
• intent="all" - All operations (default)

Example usage:
• search="pool", intent="read" - Only pool status/list endpoints
• category="ceph-pools", intent="write" - Only pool creation/modification
• search="rbd", intent="manage" - Only RBD deletion endpoints

Priority categories: ceph-pools, rbds, osds, servers, services, cluster"""

        self.mcp_tools.append(
            types.Tool(
                name=self.list_endpoints_tool,
                description=list_endpoints_desc,
                inputSchema={
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": f"Filter by category/tag. Available: {', '.join(self.top_categories[:10])}",
                        },
                        "method": {
                            "type": "string",
                            "enum": ["get", "post", "put", "delete", "patch"],
                            "description": "Filter by HTTP method",
                        },
                        "search": {
                            "type": "string",
                            "description": "Search term to filter endpoints by path or summary",
                        },
                        "intent": {
                            "type": "string",
                            "enum": ["read", "write", "manage", "all"],
                            "description": "Intent-based filtering: read (GET), write (POST/PUT/PATCH), manage (DELETE), all (default)",
                        },
                        "include_hints": {
                            "type": "boolean",
                            "description": "Include full x-llm-hints in response (default: true for first call, false after)",
                        },
                    },
                },
            )
        )

        # Base tool: call_endpoint with enhanced description
        call_endpoint_desc = """Call any API endpoint directly.

BUILT-IN FILTERING (Saves 90%+ tokens):
Instead of fetching all data and filtering client-side, use _filter_* parameters:
• _filter_status="error" - Get only items with error status
• _filter_name="~ceph.*" - Regex matching (e.g., names starting with 'ceph')
• _filter_size=">1000" - Numeric comparisons (>, <, >=, <=)
• _filter__text="timeout" - Full-text search across all string fields
• _filter__has="error_message" - Only items that have specific field
• Multiple filters can be combined: _filter_status="error"&_filter_host="node1"

Token Optimization:
• Use limit parameter for pagination (e.g., query_params={"limit": 10})
• Large responses are automatically truncated to save tokens

The endpoint metadata from list_endpoints includes x-llm-hints with:
• Purpose descriptions
• Usage examples
• Parameter details
• Request/response examples"""

        self.mcp_tools.append(
            types.Tool(
                name=self.call_endpoint_tool,
                description=call_endpoint_desc,
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "API endpoint path (e.g., /services/{id})",
                        },
                        "method": {
                            "type": "string",
                            "enum": ["get", "post", "put", "delete", "patch"],
                            "description": "HTTP method",
                        },
                        "path_params": {
                            "type": "object",
                            "description": "Path parameters as key-value pairs",
                        },
                        "query_params": {
                            "type": "object",
                            "description": "Query parameters as key-value pairs",
                        },
                        "body": {
                            "type": "object",
                            "description": "Request body (for POST, PUT, PATCH)",
                        },
                    },
                    "required": ["path", "method"],
                },
            )
        )

        # Only add get_schema tool if references aren't resolved
        if not self.resolved_references:
            self.mcp_tools.append(
                types.Tool(
                    name=self.get_schema_tool,
                    description="Get schema definition for $ref references",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "reference": {
                                "type": "string",
                                "description": "Schema reference (e.g., #/components/schemas/Service)",
                            }
                        },
                        "required": ["reference"],
                    },
                )
            )

        # Add quick-access tool for common searches
        self.mcp_tools.append(
            types.Tool(
                name="quick_find",
                description="""Quick access to most common endpoint categories.

Instantly get the most relevant endpoints without searching through hundreds of results:
• Use this when you know what type of resource you want to work with
• Returns only the most relevant endpoints for each category
• Much faster than searching through all 500+ endpoints

Categories: ceph-pools (9), rbds (17), osds, servers, services, cluster, logs""",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "resource_type": {
                            "type": "string",
                            "enum": [
                                "ceph-pools",
                                "rbds",
                                "rbd-mirror",
                                "osds",
                                "servers",
                                "services",
                                "cluster",
                                "logs",
                                "stats",
                            ],
                            "description": "Type of resource to find endpoints for",
                        },
                        "action_type": {
                            "type": "string",
                            "enum": ["list", "create", "status", "manage", "all"],
                            "description": "Type of action you want to perform (optional)",
                        },
                    },
                    "required": ["resource_type"],
                },
            )
        )

        # Generate category tools for top categories
        for category in self.top_categories:
            self._generate_category_tool(category)

        logger.info(f"Generated {len(self.mcp_tools)} tools total (hybrid mode)")

    def _extract_schema_parameters(self, endpoint):
        """
        Extract parameter hints from OpenAPI schema when x-llm-hints are missing.
        Returns parameter names and their metadata from the endpoint definition.
        Fully resolves schema references and nested structures.
        """
        params = {}

        # Extract query/path parameters from the parameters array
        for param in endpoint.get("parameters", []):
            param_name = param.get("name", "")
            if param_name:
                params[param_name] = {
                    "type": param.get("in", "unknown"),
                    "description": param.get("description", ""),
                    "required": param.get("required", False),
                }

        # Extract body parameters from requestBody schema
        request_body = endpoint.get("requestBody", {})
        if request_body:
            content = request_body.get("content", {})
            json_content = content.get("application/json", {})
            schema = json_content.get("schema", {})

            # Recursively extract parameters from schema
            self._extract_schema_properties(schema, params, prefix="", depth=0)

        return params

    def _extract_schema_properties(self, schema, params, prefix="", depth=0):
        """
        Recursively extract parameters from a schema, resolving references and nested structures.
        """
        # Prevent infinite recursion
        if depth > 5:
            return

        # Handle schema references
        if schema.get("$ref"):
            ref_path = schema["$ref"]
            if ref_path.startswith("#/components/schemas/"):
                schema_name = ref_path.split("/")[-1]
                resolved_schema = (
                    self.api_spec.get("components", {})
                    .get("schemas", {})
                    .get(schema_name, {})
                )
                if resolved_schema:
                    self._extract_schema_properties(
                        resolved_schema, params, prefix, depth + 1
                    )
                return

        # Handle direct properties
        if schema.get("properties"):
            required_fields = schema.get("required", [])
            for prop_name, prop_def in schema["properties"].items():
                full_name = f"{prefix}{prop_name}" if prefix else prop_name

                # Get base description
                description = prop_def.get("description", "")

                # Handle array types (like osds[])
                if prop_def.get("type") == "array":
                    array_items = prop_def.get("items", {})
                    description = (
                        description or f"Array of {array_items.get('type', 'items')}"
                    )

                    # Add the array parameter itself
                    params[full_name] = {
                        "type": "body",
                        "description": description,
                        "required": prop_name in required_fields,
                    }

                    # Recursively extract array item properties with [] notation
                    if array_items:
                        self._extract_schema_properties(
                            array_items,
                            params,
                            prefix=f"{full_name}[].",
                            depth=depth + 1,
                        )

                # Handle object types
                elif prop_def.get("type") == "object" or prop_def.get("properties"):
                    # Add the object parameter itself
                    params[full_name] = {
                        "type": "body",
                        "description": description or "Object with nested properties",
                        "required": prop_name in required_fields,
                    }

                    # Recursively extract object properties with dot notation
                    self._extract_schema_properties(
                        prop_def, params, prefix=f"{full_name}.", depth=depth + 1
                    )

                # Handle schema references in properties
                elif prop_def.get("$ref"):
                    # Add the reference parameter
                    params[full_name] = {
                        "type": "body",
                        "description": description
                        or f"Reference to {prop_def['$ref'].split('/')[-1]}",
                        "required": prop_name in required_fields,
                    }

                    # Recursively resolve the reference
                    self._extract_schema_properties(
                        prop_def, params, prefix=f"{full_name}.", depth=depth + 1
                    )

                # Handle primitive types
                else:
                    param_type = prop_def.get("type", "unknown")
                    format_info = prop_def.get("format", "")
                    if format_info:
                        param_type = f"{param_type} ({format_info})"

                    params[full_name] = {
                        "type": "body",
                        "description": description or f"{param_type} value",
                        "required": prop_name in required_fields,
                    }

    def _generate_category_tool(self, category: str):
        """
        Generate a category-specific tool for a given tag/category.
        """
        endpoints = self.category_endpoints.get(category, [])
        if not endpoints:
            return

        # Analyze available operations
        methods = set(ep["method"] for ep in endpoints)
        has_list = any(
            ep["method"] == "get" and "{" not in ep["path"] for ep in endpoints
        )
        # Only consider "get" action if there's a simple resource endpoint like /resource/{id}
        # Exclude complex paths like /resource/status/{timestamp} or /resource/action/{param}
        has_get = any(
            ep["method"] == "get"
            and "{" in ep["path"]
            and ep["path"].count("{") == 1  # Only one parameter
            and not any(
                word in ep["path"].lower()
                for word in ["status", "history", "action", "config"]
            )  # Exclude status/action endpoints
            for ep in endpoints
        )
        has_create = "post" in methods
        has_update = "put" in methods or "patch" in methods
        has_delete = "delete" in methods

        # Build actions list
        actions = []
        if has_list:
            actions.append("list")
        if has_get:
            actions.append("get")
        if has_create:
            actions.append("create")
        if has_update:
            actions.append("update")
        if has_delete:
            actions.append("delete")

        tool_name = f"manage_{category.replace('-', '_')}"
        description = (
            f"Manage {category} resources. Available actions: {', '.join(actions)}"
        )

        # Extract ALL LLM hints for comprehensive tool description
        hint_purposes = []
        hint_usages = []
        hint_examples = []
        hint_params = []
        hint_failure_modes = []
        hint_error_handling = []
        hint_workflow_guidance = {}
        hint_rate_limits = []
        hint_retry_strategies = []
        hint_poll_intervals = []
        hint_cache_hints = []
        hint_related_endpoints = []
        hint_ceph_integration = {}
        hint_workflow_dependencies = {}
        has_confirmations = False
        has_token_hints = False

        for ep in endpoints:  # Check ALL endpoints for hints
            hints = ep.get("llm_hints", {})
            if hints:
                # Collect purposes
                if hints.get("purpose") and len(hint_purposes) < 3:
                    hint_purposes.append(hints["purpose"])

                # Collect usage examples
                if hints.get("usage"):
                    for usage in hints["usage"]:
                        if len(hint_usages) < 5:
                            hint_usages.append(usage)

                # Collect request examples
                if hints.get("request_examples") and len(hint_examples) < 2:
                    hint_examples.append(hints["request_examples"])

                # Collect parameter details
                if hints.get("parameter_details"):
                    hint_params.extend(list(hints["parameter_details"].keys()))

                # Collect failure modes
                if hints.get("failure_modes"):
                    hint_failure_modes.extend(hints["failure_modes"][:3])

                # Collect error handling
                if hints.get("error_handling"):
                    hint_error_handling.extend(hints["error_handling"][:2])

                # Collect workflow guidance
                if hints.get("workflow_guidance"):
                    hint_workflow_guidance.update(hints["workflow_guidance"])

                # Collect rate limits
                if hints.get("rate_limit"):
                    limit_info = hints["rate_limit"]
                    if isinstance(limit_info, dict):
                        hint_rate_limits.append(
                            f"{limit_info.get('limit', 'N/A')}/{limit_info.get('window_seconds', 60)}s"
                        )

                # Collect retry strategy
                if hints.get("retry_strategy"):
                    hint_retry_strategies.append(hints["retry_strategy"])

                # Collect poll intervals
                if hints.get("recommended_poll_interval"):
                    poll_info = hints["recommended_poll_interval"]
                    if isinstance(poll_info, dict):
                        hint_poll_intervals.append(
                            f"{poll_info.get('value', 'N/A')} {poll_info.get('unit', 'seconds')}"
                        )

                # Collect cache hints
                if hints.get("cache_hint"):
                    hint_cache_hints.append(hints["cache_hint"])

                # Collect related endpoints
                if hints.get("related_endpoints"):
                    hint_related_endpoints.extend(hints["related_endpoints"][:3])

                # Collect ceph_integration (NEW)
                if hints.get("ceph_integration"):
                    ceph_int = hints["ceph_integration"]
                    if isinstance(ceph_int, dict):
                        hint_ceph_integration.update(ceph_int)

                # Collect workflow_dependencies (NEW)
                if hints.get("workflow_dependencies"):
                    workflow_deps = hints["workflow_dependencies"]
                    if isinstance(workflow_deps, dict):
                        hint_workflow_dependencies.update(workflow_deps)

                if hints.get("requires_confirmation"):
                    has_confirmations = True

                if hints.get("response_shape") or hints.get("token_optimization"):
                    has_token_hints = True

        # If no parameter hints from x-llm-hints, extract from schema
        if not hint_params:
            for ep in endpoints:
                schema_params = self._extract_schema_parameters(ep)
                hint_params.extend(schema_params.keys())

        # Build enhanced description with ALL hints (clean, professional format)
        if hint_purposes:
            description += f"\n\nPurpose: {hint_purposes[0][:200]}"

        if hint_usages:
            description += f"\n\nCommon usage:\n• " + "\n• ".join(hint_usages[:3])

        # Add workflow guidance if available
        if hint_workflow_guidance:
            if hint_workflow_guidance.get("pre_check"):
                description += (
                    f"\n\nPre-check: {hint_workflow_guidance['pre_check'][:150]}"
                )
            if hint_workflow_guidance.get("post_action"):
                description += (
                    f"\n\nPost-action: {hint_workflow_guidance['post_action'][:150]}"
                )

        # Add failure modes
        if hint_failure_modes:
            unique_failures = list(set(hint_failure_modes))[:2]
            description += f"\n\nFailure modes:\n• " + "\n• ".join(unique_failures)

        # Add error handling
        if hint_error_handling:
            error_info = []
            for error in hint_error_handling[:2]:
                if isinstance(error, dict):
                    code = error.get("code", "N/A")
                    action = error.get("action", "No action specified")[:100]
                    error_info.append(f"{code}: {action}")
            if error_info:
                description += f"\n\nError handling:\n• " + "\n• ".join(error_info)

        # Add rate limits
        if hint_rate_limits:
            unique_limits = list(set(hint_rate_limits))[:2]
            description += f"\n\nRate limits: {', '.join(unique_limits)}"

        # Add retry strategy
        if hint_retry_strategies:
            unique_strategies = list(set(hint_retry_strategies))
            description += f"\n\nRetry strategy: {', '.join(unique_strategies)}"

        # Add recommended polling intervals
        if hint_poll_intervals:
            unique_intervals = list(set(hint_poll_intervals))
            description += f"\n\nPoll interval: {', '.join(unique_intervals)}"

        # Add cache hints
        if hint_cache_hints:
            unique_cache = list(set(hint_cache_hints))
            description += f"\n\nCache: {', '.join(unique_cache)}"

        # Add related endpoints
        if hint_related_endpoints:
            unique_related = list(set(hint_related_endpoints))[:3]
            description += f"\n\nRelated endpoints: {', '.join(unique_related)}"

        # Add Ceph integration steps (NEW)
        if hint_ceph_integration:
            if hint_ceph_integration.get("automatic_steps"):
                steps = hint_ceph_integration["automatic_steps"]
                description += "\n\nCeph Integration (automatic steps):"
                for step in steps[:5]:  # Limit to 5 steps
                    description += f"\n• {step}"

        # Add workflow dependencies (NEW)
        if hint_workflow_dependencies:
            if hint_workflow_dependencies.get("prerequisite"):
                description += f"\n\nPrerequisite: {hint_workflow_dependencies['prerequisite'][:200]}"
            if hint_workflow_dependencies.get("order"):
                description += (
                    f"\nWorkflow order: {hint_workflow_dependencies['order'][:150]}"
                )

        if hint_params:
            unique_params = list(set(hint_params))[:5]
            description += f"\n\nKey parameters: {', '.join(unique_params)}"

        if hint_examples:
            description += "\n\nRequest examples available via list_endpoints"

        if has_token_hints:
            description += "\n\nToken optimization: Use filters and pagination"

        if has_confirmations:
            description += "\n\nNote: Some operations require confirmation"

        # Add endpoint examples
        example_ops = endpoints[:3]
        if example_ops:
            examples = [f"{ep['method'].upper()} {ep['path']}" for ep in example_ops]
            if examples:
                description += f"\n\nEndpoints: {'; '.join(examples)}"

        input_schema = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": actions,
                    "description": f"Action to perform on {category}",
                },
                "resource_id": {
                    "type": "string",
                    "description": f"ID of the {category} resource (for get, update, delete)",
                },
                "filters": {
                    "type": "object",
                    "description": "Filters for list action (query parameters)",
                },
                "data": {
                    "type": "object",
                    "description": "Data for create or update actions",
                },
            },
            "required": ["action"],
        }

        self.mcp_tools.append(
            types.Tool(
                name=tool_name,
                description=description[
                    :1500
                ],  # Increased limit to include x-llm-hints
                inputSchema=input_schema,
            )
        )

    def _prepare_category_tools_only(self):
        """
        Prepare only category-based tools (no base tools).
        """
        for category in self.top_categories:
            self._generate_category_tool(category)

        logger.info(
            f"Generated {len(self.mcp_tools)} category tools (categories_only mode)"
        )

    def _prepare_api_tools(self):
        """
        Prepare the MCP tools to list the API, resolve references to schemas, and call the API.
        This will populate self.mcp_tools with these tools, but ignore self.tools, as there are no dynamically generated tools here.
        This is only called when not generating a tool per endpoint. The LLM is expected to list the endpoints instead via a tool.
        """

        # These 3 variables just store the names of the tools, they are used later when the LLM wants to use the tools.
        self.get_apis_tool = "list_api_endpoints"
        self.resolve_references_tool = "get_reference_schema"
        self.call_api_tool = "call_api_endpoint"
        self.mcp_tools = [
            types.Tool(
                name=self.get_apis_tool,
                description="Lists available croit cluster API endpoints in the OpenAPI schema format. "
                + "These can then be called with call_api_endpoint. Some offer pagination, use it when available.",
                inputSchema={"type": "object", "properties": {}},
            ),
            types.Tool(
                name=self.resolve_references_tool,
                description="Resolves $ref schemas. This tool should be called whenever $ref is encountered to get the actual schema.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "reference_path": {
                            "type": "string",
                            "description": 'The reference string, e.g. "#/components/schemas/PaginationRequest"',
                        }
                    },
                    "required": ["reference_path"],
                },
                outputSchema={
                    "type": "object",
                    "description": "The resolved reference schema.",
                },
            ),
            types.Tool(
                name=self.call_api_tool,
                description="Calls the provided API endpoint and returns its response.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "endpoint": {
                            "type": "string",
                            "description": "The endpoint as provided by list_api_endpoints, with path parameters already filled in.",
                        },
                        "method": {
                            "type": "string",
                            "description": "The HTTP method to use, e.g. get, post, etc.",
                        },
                        "body": {
                            "type": "object",
                            "description": "Request body (only if the endpoint expects a body).",
                        },
                        "queryParams": {
                            "type": "array",
                            "description": "List of query parameters to send with the request.",
                            "items": {
                                "type": "object",
                                "description": "A single query parameter.",
                                "properties": {
                                    "name": {
                                        "type": "string",
                                        "description": "Name of the parameter.",
                                    },
                                    "value": {
                                        "description": "Value of the parameter, may be a simple string, but can also be a JSON object.",
                                    },
                                },
                            },
                        },
                    },
                    "required": ["endpoint"],
                },
                outputSchema={
                    "type": "object",
                    "description": "The resolved reference schema.",
                },
            ),
        ]

    def _add_log_search_tools(self):
        """Add log search tools to the available tools"""
        if not LOG_TOOLS_AVAILABLE:
            return

        # Get current time info for LLM context
        import time
        from datetime import datetime

        current_unix = int(time.time())
        current_human = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        one_hour_ago = current_unix - 3600
        one_day_ago = current_unix - 86400

        time_context = f"""

CURRENT TIME CONTEXT (for timestamp calculations):
• Current Unix timestamp: {current_unix}
• Current time (human): {current_human}
• 1 hour ago: {one_hour_ago}
• 1 day ago: {one_day_ago}
• Use these values when constructing start_timestamp/end_timestamp queries"""

        for tool_def in LOG_SEARCH_TOOLS:
            # Add current time context to description
            enhanced_description = tool_def["description"] + time_context

            tool = types.Tool(
                name=tool_def["name"],
                description=enhanced_description,
                inputSchema=tool_def["inputSchema"],
            )
            self.mcp_tools.append(tool)
            logger.info(f"Added log search tool: {tool_def['name']}")

    async def handle_list_tools(self) -> list[types.Tool]:
        """Return available tools."""
        logger.info(f"Providing {len(self.mcp_tools)} tools")
        return self.mcp_tools

    async def _make_api_call(
        self,
        url: str,
        method: str,
        kwargs: Dict,
        filters: Dict = None,
    ) -> dict[str, Any]:
        """
        Helper function to make the actual API call.
        This function is async, make sure to call it with await before returning the result.
        """
        # Auto-add default limits for list operations to prevent token overflow
        if TokenOptimizer.should_optimize(url, method):
            params = kwargs.get("params", {})
            params = TokenOptimizer.add_default_limit(url, params)
            kwargs["params"] = params

        logger.info(f"Calling {method} {url}")
        if filters:
            logger.info(f"With filters: {filters}")
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"kwargs: {json.dumps(kwargs, indent=2)}")
        try:
            async with self.session.request(method.upper(), url, **kwargs) as resp:
                response_text = await resp.text()
                try:
                    response_data = json.loads(response_text) if response_text else None
                except:
                    response_data = response_text

                # Apply filters first (before truncation)
                if resp.status >= 200 and resp.status < 300 and filters:
                    response_data = TokenOptimizer.apply_filters(response_data, filters)

                # Then apply token optimization to the response
                if resp.status >= 200 and resp.status < 300:
                    response_data = TokenOptimizer.truncate_response(response_data, url)

                # This matches our schema defined in self._build_response_schema
                schema_response = {
                    "code": resp.status,
                }

                # Add result or error based on status
                if resp.status >= 200 and resp.status < 300:
                    schema_response["result"] = response_data
                else:
                    schema_response["error"] = (
                        f"{resp.reason}: {response_data}"
                        if response_data
                        else resp.reason
                    )

                return schema_response
        except Exception as e:
            logger.error(f"Request error: {e}")
            schema_response = {"code": 500, "error": f"Request failed: {str(e)}"}
            return schema_response

    async def handle_api_call_tool(
        self,
        name: str,
        arguments: Dict,
    ) -> dict[str, Any]:
        """
        Handle the tools to let the LLM inspect and call the croit API directly.
        This is the handler when we don't map each endpoint to a tool, but only offer a few tools to list and call the API directly.
        """
        logger.info(f"Tool call {name}")

        # Handle log search tools
        if self.enable_log_tools:
            if name == "croit_log_search":
                return await self._handle_log_search(arguments)
            elif name == "croit_log_check":
                return await self._handle_log_check(arguments)

        if name == self.resolve_references_tool:
            resolved = self._resolve_reference_schema(
                ref_path=arguments["reference_path"]
            )
            return resolved
        if name == self.get_apis_tool:
            if self.offer_whole_spec:
                return self.api_spec
            return self.api_spec.get("paths", {})
        if name != self.call_api_tool:
            raise RuntimeError(f"Tool {name} not found")

        # Rest of the code is the tool for call_api_tool.
        endpoint = arguments["endpoint"]
        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint
        url = f"{self.host}/api{endpoint}"
        method = arguments["method"]

        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        body = None
        if "body" in arguments:
            body = arguments["body"]

        query_params = None
        if "queryParams" in arguments:
            query_params = {}
            for param in arguments["queryParams"]:
                value = param["value"]
                if isinstance(value, dict):
                    value = json.dumps(value)
                query_params[param["name"]] = value

        kwargs = {"headers": headers, "ssl": self.ssl}
        if query_params is not None:
            kwargs["params"] = query_params
        if body is not None:
            kwargs["json"] = body
        return await self._make_api_call(url=url, method=method, kwargs=kwargs)

    async def run(self):
        """Run the MCP server."""
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="mcp-croit-ceph",
                    server_version="0.2.0",
                    capabilities=self.server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                    instructions=self.instructions,
                ),
            )

    async def handle_hybrid_tool(
        self,
        name: str,
        arguments: Dict,
    ) -> dict[str, Any]:
        """
        Handle hybrid mode tools: base tools and category tools.
        """
        logger.info(f"Hybrid tool call: {name} with args {arguments}")

        # Handle log search tools
        if self.enable_log_tools:
            if name == "croit_log_search":
                return await self._handle_log_search(arguments)
            elif name == "croit_log_check":
                return await self._handle_log_check(arguments)

        # Handle base tools
        if name == self.list_endpoints_tool:
            return self._list_endpoints_filtered(arguments)

        if name == "quick_find":
            return self._quick_find_endpoints(arguments)

        if name == self.call_endpoint_tool:
            return await self._call_endpoint_direct(arguments)

        if hasattr(self, "get_schema_tool") and name == self.get_schema_tool:
            return self._resolve_reference_schema(ref_path=arguments["reference"])

        # Handle category tools
        if name.startswith("manage_"):
            return await self._handle_category_tool(name, arguments)

        raise RuntimeError(f"Unknown tool: {name}")

    async def handle_category_tool(
        self,
        name: str,
        arguments: Dict,
    ) -> dict[str, Any]:
        """
        Handle category-only mode tools.
        """
        logger.info(f"Category tool call: {name} with args {arguments}")

        # Handle log search tools
        if self.enable_log_tools:
            if name == "croit_log_search":
                return await self._handle_log_search(arguments)
            elif name == "croit_log_check":
                return await self._handle_log_check(arguments)

        if name.startswith("manage_"):
            return await self._handle_category_tool(name, arguments)

        raise RuntimeError(f"Unknown tool: {name}")

    async def _handle_log_search(self, arguments: Dict) -> dict[str, Any]:
        """Handle log search tool call"""
        # Extract host, port, and protocol from self.host
        import re

        match = re.match(r"(https?)://([^:]+):?(\d+)?", self.host)
        if match:
            protocol = match.group(1)
            host = match.group(2)
            port = (
                int(match.group(3))
                if match.group(3)
                else (443 if protocol == "https" else 8080)
            )
            use_ssl = protocol == "https"
        else:
            host = self.host
            port = 8080
            use_ssl = False

        # Add API token and SSL info to arguments
        arguments_with_token = arguments.copy()
        arguments_with_token["api_token"] = self.api_token
        arguments_with_token["use_ssl"] = use_ssl

        return await handle_log_search(arguments_with_token, host, port)

    async def _handle_log_check(self, arguments: Dict) -> dict[str, Any]:
        """Handle log check tool call"""
        # Extract host, port, and protocol from self.host
        import re

        match = re.match(r"(https?)://([^:]+):?(\d+)?", self.host)
        if match:
            protocol = match.group(1)
            host = match.group(2)
            port = (
                int(match.group(3))
                if match.group(3)
                else (443 if protocol == "https" else 8080)
            )
            use_ssl = protocol == "https"
        else:
            host = self.host
            port = 8080
            use_ssl = False

        # Add API token and SSL info to arguments
        arguments_with_token = arguments.copy()
        arguments_with_token["api_token"] = self.api_token
        arguments_with_token["use_ssl"] = use_ssl

        return await handle_log_check(arguments_with_token, host, port)

    async def _handle_category_tool(
        self,
        name: str,
        arguments: Dict,
    ) -> dict[str, Any]:
        """
        Handle a category-specific tool call.
        Maps the action to the appropriate endpoint and makes the API call.
        """
        # Extract category from tool name (manage_services -> services)
        category = name.replace("manage_", "").replace("_", "-")

        if category not in self.category_endpoints:
            return {"error": f"Category {category} not found"}

        action = arguments.get("action")
        resource_id = arguments.get("resource_id")
        filters = arguments.get("filters", {})
        data = arguments.get("data", {})

        # Find matching endpoint based on action
        endpoints = self.category_endpoints[category]
        target_endpoint = None

        for ep in endpoints:
            path = ep["path"]
            method = ep["method"]

            # Match action to endpoint pattern
            if action == "list" and method == "get" and "{" not in path:
                target_endpoint = ep
                break
            elif action == "get" and method == "get" and "{" in path and resource_id:
                # Ensure it's a simple resource endpoint, not a status/action endpoint
                if path.count("{") == 1 and not any(
                    word in path.lower()
                    for word in ["status", "history", "action", "config"]
                ):
                    target_endpoint = ep
                    break
            elif action == "create" and method == "post" and "{" not in path:
                target_endpoint = ep
                break
            elif (
                action == "update"
                and method in ["put", "patch"]
                and "{" in path
                and resource_id
            ):
                target_endpoint = ep
                break
            elif (
                action == "delete"
                and method == "delete"
                and "{" in path
                and resource_id
            ):
                target_endpoint = ep
                break

        if not target_endpoint:
            return {
                "error": f"No endpoint found for action '{action}' in category '{category}'"
            }

        # Build the request
        path = target_endpoint["path"]
        method = target_endpoint["method"]

        # Replace path parameters
        if resource_id and "{" in path:
            # Find parameter name (e.g., {id}, {name}, etc.)
            import re

            params = re.findall(r"\{([^}]+)\}", path)
            if params:
                path = path.replace(f"{{{params[0]}}}", str(resource_id))

        # Make the API call
        url = f"{self.host}/api{path}"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
        }

        kwargs = {"headers": headers, "ssl": self.ssl}

        if action == "list":
            # Prepare query parameters
            params = filters.copy() if filters else {}

            # Add default pagination for endpoints that require it
            if "pagination" not in params:
                # Check if this endpoint needs pagination based on OpenAPI spec
                endpoint_def = None
                for ep in self.category_endpoints.get(category, []):
                    if ep["method"] == method and ep["path"] == path:
                        endpoint_def = ep
                        break

                if endpoint_def and self._endpoint_requires_pagination(
                    endpoint_def["path"]
                ):
                    default_pagination = self._get_default_pagination(category)
                    params["pagination"] = json.dumps(
                        default_pagination, separators=(",", ":")
                    )

            if params:
                kwargs["params"] = params
        elif action in ["create", "update"] and data:
            headers["Content-Type"] = "application/json"
            kwargs["json"] = data

        result = await self._make_api_call(url=url, method=method, kwargs=kwargs)

        # Add context about the operation and LLM hints
        context = {
            "category": category,
            "action": action,
            "endpoint": path,
            "method": method.upper(),
        }

        # Include ALL LLM hints if available - let the AI use what it needs
        if target_endpoint.get("llm_hints"):
            context["llm_hints"] = target_endpoint["llm_hints"]

        result["_operation"] = context

        return result

    def _list_endpoints_filtered(self, arguments: Dict) -> dict[str, Any]:
        """
        List API endpoints with optional filtering and smart prioritization.
        """
        category_filter = arguments.get("category")
        method_filter = arguments.get("method")
        search_term = arguments.get("search", "").lower()
        intent_filter = arguments.get("intent", "all")

        # Determine if we should include hints (default: true for first call, false after)
        include_hints = arguments.get("include_hints")
        if include_hints is None:
            include_hints = not self.hints_shown
            self.hints_shown = True  # Mark as shown after first call

        results = []
        priority_results = []

        # Define priority categories for common searches
        priority_mapping = {
            "pool": ["ceph-pools"],  # Prioritize Ceph pools over DAOS pools
            "rbd": ["rbds", "rbd-mirror"],
            "osd": [
                "crush",
                "services",
                "maintenance",
                "servers",
                "disks",
            ],  # OSD endpoints are spread across multiple tags
            "server": ["servers"],
            "service": ["services"],
            "cluster": ["cluster"],
            "log": ["logs"],
        }

        # Map intent to HTTP methods
        intent_methods = {
            "read": ["get"],
            "write": ["post", "put", "patch"],
            "manage": ["delete"],
            "all": ["get", "post", "put", "delete", "patch"],
        }

        for path, methods in self.api_spec.get("paths", {}).items():
            for method, operation in methods.items():
                if method.lower() not in ["get", "post", "put", "delete", "patch"]:
                    continue

                # Apply filters
                if method_filter and method.lower() != method_filter.lower():
                    continue

                # Apply intent filter
                allowed_methods = intent_methods.get(
                    intent_filter, intent_methods["all"]
                )
                if method.lower() not in allowed_methods:
                    continue

                tags = operation.get("tags", [])
                if category_filter and category_filter not in tags:
                    continue

                # Skip DAOS endpoints if not enabled
                if not self.enable_daos and "daos" in tags:
                    continue

                # Skip specialty features if not enabled
                if not self.enable_specialty_features and any(
                    tag in tags for tag in ["rbd-mirror", "qos-settings", "ceph-keys"]
                ):
                    continue

                # Skip deprecated endpoints
                if operation.get("deprecated", False):
                    continue

                summary = operation.get("summary", "")
                if search_term:
                    # Support both full phrase and individual word matching
                    path_lower = path.lower()
                    summary_lower = summary.lower()

                    # Try exact phrase match first
                    if search_term in path_lower or search_term in summary_lower:
                        pass  # Found exact match, continue
                    else:
                        # Try individual word matching for multi-word searches
                        search_words = search_term.split()
                        if len(search_words) > 1:
                            # All words must be found somewhere in path or summary
                            if not all(
                                word in path_lower or word in summary_lower
                                for word in search_words
                            ):
                                continue
                        else:
                            # Single word that didn't match exactly, skip
                            continue

                # Extract key LLM hints
                llm_hints = operation.get("x-llm-hints", {})
                endpoint_data = {
                    "path": path,
                    "method": method.upper(),
                    "operationId": operation.get("operationId", ""),
                    "summary": summary,
                    "tags": tags,
                    "deprecated": operation.get("deprecated", False),
                }

                # Add ALL LLM hints if present - let the AI decide what's important
                # Only include if requested to reduce token usage
                if llm_hints and include_hints:
                    endpoint_data["llm_hints"] = llm_hints
                elif llm_hints and not include_hints:
                    # Just include a summary indicator
                    endpoint_data["has_hints"] = True

                # Check if this should be prioritized
                is_priority = False
                if search_term:
                    priority_tags = priority_mapping.get(search_term, [])
                    if any(tag in priority_tags for tag in tags):
                        is_priority = True
                    # Also prioritize if search term appears prominently in path or summary
                    elif (
                        search_term in path.lower()
                        and path.lower().count(search_term) > 0
                    ) or (
                        search_term in summary.lower() and len(summary.split()) < 10
                    ):  # Short, focused descriptions
                        is_priority = True

                if is_priority:
                    priority_results.append(endpoint_data)
                else:
                    results.append(endpoint_data)

        # Combine priority results first, then others
        all_results = priority_results + results

        # Smart truncation - show more priority results
        if len(priority_results) > 0:
            max_results = min(
                50, 30 + len(priority_results)
            )  # Show at least priority + some others
        else:
            max_results = 50  # Default limit when no priorities

        # Add feature filtering info
        filtering_info = ["Deprecated endpoints excluded"]
        if not self.enable_daos:
            filtering_info.append("DAOS endpoints excluded")
        if not self.enable_specialty_features:
            filtering_info.append("Specialty features excluded")
        if intent_filter != "all":
            filtering_info.append(f"Intent filter: {intent_filter}")

        result = {
            "total": len(all_results),
            "priority_count": len(priority_results),
            "endpoints": all_results[:max_results],
            "truncated": len(all_results) > max_results,
            "optimization_note": (
                f"Prioritized {len(priority_results)} most relevant results"
                if priority_results
                else "No prioritization applied"
            ),
            "filtering_applied": filtering_info if filtering_info else ["None"],
            "intent_filter": intent_filter,
            "feature_flags": {
                "daos_enabled": self.enable_daos,
                "specialty_features_enabled": self.enable_specialty_features,
            },
        }

        # Add hint about hints availability if not included
        if not include_hints and any(
            ep.get("has_hints") for ep in all_results[:max_results]
        ):
            result["hints_note"] = (
                "x-llm-hints available but not shown (saves tokens). Use include_hints=true to see them."
            )

        return result

    async def _call_endpoint_direct(self, arguments: Dict) -> dict[str, Any]:
        """
        Call an API endpoint directly with provided parameters.
        """
        path = arguments.get("path")
        method = arguments.get("method", "get").lower()
        path_params = arguments.get("path_params", {})
        query_params = arguments.get("query_params", {})
        body = arguments.get("body")

        # Replace path parameters
        for key, value in path_params.items():
            path = path.replace(f"{{{key}}}", str(value))

        # Add default pagination for endpoints that require it
        if method == "get" and query_params is not None:
            query_params = query_params.copy()  # Don't modify the original
            if "pagination" not in query_params and self._endpoint_requires_pagination(
                path
            ):
                # Determine category from endpoint path for appropriate defaults
                category = self._detect_category_from_path(path)
                default_pagination = self._get_default_pagination(category)
                query_params["pagination"] = json.dumps(
                    default_pagination, separators=(",", ":")
                )

        url = f"{self.host}/api{path}"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
        }

        kwargs = {"headers": headers, "ssl": self.ssl}

        if query_params:
            kwargs["params"] = query_params

        if body and method in ["post", "put", "patch", "delete"]:
            headers["Content-Type"] = "application/json"
            kwargs["json"] = body

        return await self._make_api_call(url=url, method=method, kwargs=kwargs)

    def _quick_find_endpoints(self, arguments: Dict) -> dict[str, Any]:
        """
        Quick access to most relevant endpoints for a specific resource type.
        """
        resource_type = arguments.get("resource_type")
        action_type = arguments.get("action_type", "all")

        # For quick_find, never include full hints to save tokens
        include_hints = False

        # Map resource types to exact categories
        category_mapping = {
            "ceph-pools": "ceph-pools",
            "rbds": "rbds",
            "rbd-mirror": "rbd-mirror",
            "osds": [
                "crush",
                "services",
                "maintenance",
                "servers",
                "disks",
            ],  # OSD is spread across categories
            "servers": "servers",
            "services": "services",
            "cluster": "cluster",
            "logs": "logs",
            "stats": "stats",
        }

        target_categories = category_mapping.get(resource_type)
        if not target_categories:
            return {"error": f"Unknown resource type: {resource_type}"}

        # Handle both single category and list of categories
        if isinstance(target_categories, str):
            target_categories = [target_categories]

        results = []
        for path, methods in self.api_spec.get("paths", {}).items():
            for method, operation in methods.items():
                if method.lower() not in ["get", "post", "put", "delete", "patch"]:
                    continue

                tags = operation.get("tags", [])
                # Check if any of the target categories match
                if not any(cat in tags for cat in target_categories):
                    continue

                # Skip deprecated endpoints
                if operation.get("deprecated", False):
                    continue

                # Filter by action type if specified
                if action_type != "all":
                    method_lower = method.lower()
                    if action_type == "list" and not (
                        method_lower == "get" and "{" not in path
                    ):
                        continue
                    elif action_type == "create" and method_lower != "post":
                        continue
                    elif action_type == "status" and "status" not in path.lower():
                        continue
                    elif action_type == "manage" and method_lower == "get":
                        continue

                # Build endpoint data
                llm_hints = operation.get("x-llm-hints", {})
                endpoint_data = {
                    "path": path,
                    "method": method.upper(),
                    "operationId": operation.get("operationId", ""),
                    "summary": operation.get("summary", ""),
                    "tags": tags,
                    "deprecated": operation.get("deprecated", False),
                }

                # Only show that hints exist, not the full content (saves tokens)
                if llm_hints:
                    endpoint_data["has_hints"] = True

                results.append(endpoint_data)

        # Sort by relevance (GET endpoints first, then by path simplicity)
        results.sort(
            key=lambda x: (
                0 if x["method"] == "GET" else 1,
                x["path"].count("/"),
                x["path"],
            )
        )

        return {
            "resource_type": resource_type,
            "action_filter": action_type,
            "total": len(results),
            "endpoints": results[:20],  # Limit to top 20 most relevant
            "truncated": len(results) > 20,
            "optimization_note": f"Showing most relevant endpoints for {resource_type}",
            "hints_note": "x-llm-hints not shown in quick_find (saves tokens). Use list_endpoints with include_hints=true for full hints.",
        }

    def _endpoint_requires_pagination(self, endpoint_path: str) -> bool:
        """
        Check if an endpoint requires pagination parameter based on OpenAPI spec.
        Supports both exact paths and parameterized paths.
        """
        # First try exact match
        endpoint_spec = (
            self.api_spec.get("paths", {}).get(endpoint_path, {}).get("get", {})
        )

        if endpoint_spec:
            parameters = endpoint_spec.get("parameters", [])
            for param in parameters:
                if param.get("name") == "pagination" and param.get("required", False):
                    return True

        # If no exact match, try pattern matching for parameterized paths
        for spec_path, methods in self.api_spec.get("paths", {}).items():
            if self._path_matches_template(endpoint_path, spec_path):
                get_spec = methods.get("get", {})
                parameters = get_spec.get("parameters", [])
                for param in parameters:
                    if param.get("name") == "pagination" and param.get(
                        "required", False
                    ):
                        return True

        return False

    def _path_matches_template(self, actual_path: str, template_path: str) -> bool:
        """
        Check if an actual path matches a template path with parameters.
        e.g., '/pools/test-pool/rbds' matches '/pools/{pool}/rbds'
        """
        import re

        # Convert template to regex pattern
        # Replace {param} with regex that matches path segments
        pattern = re.escape(template_path)
        pattern = re.sub(r"\\\{[^}]+\\\}", r"[^/]+", pattern)
        pattern = f"^{pattern}$"

        return bool(re.match(pattern, actual_path))

    def _detect_category_from_path(self, path: str) -> str:
        """
        Detect the likely category from an endpoint path.
        """
        path_lower = path.lower()

        # RBD-related endpoints
        if "/rbds" in path_lower or "/rbd-" in path_lower:
            return "rbds"

        # Pool-related endpoints
        if "/pools" in path_lower:
            return "ceph-pools"

        # Other patterns
        if "/crush" in path_lower:
            return "crush"
        if "/servers" in path_lower:
            return "servers"
        if "/services" in path_lower:
            return "services"

        # Default
        return "generic"

    def _get_default_pagination(self, category: str) -> dict:
        """
        Get appropriate default pagination for a category.
        """
        # Category-specific defaults
        if category == "rbds":
            return {
                "limit": 20,
                "after": 0,
                "where": {},
                "sortBy": [["pool", "ASC"], ["namespace", "ASC"], ["name", "ASC"]],
            }

        # Generic default
        return {"limit": 20, "after": 0, "where": {}, "sortBy": []}

    async def cleanup(self):
        """Cleanup resources."""
        if self.session:
            await self.session.close()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["hybrid", "base_only", "categories_only"],
        default="hybrid",
        help="Tool generation mode (default: hybrid)",
    )
    parser.add_argument(
        "--no-resolve-references",
        action="store_false",
        dest="resolve_references",
        help="Don't resolve $refs in the API spec.",
    )
    parser.add_argument(
        "--offer-whole-spec",
        action="store_true",
        help="Offer the entire API spec in the list_api_endpoints tool.",
    )
    parser.add_argument(
        "--no-permission-check",
        action="store_false",
        dest="check_permissions",
        help="Skip permission checking for categories (faster startup but may include inaccessible tools)",
    )
    parser.add_argument(
        "--max-category-tools",
        type=int,
        default=10,
        help="Maximum number of category tools to generate (default: 10)",
    )
    parser.add_argument(
        "--openapi-file",
        type=str,
        default=os.environ.get("OPENAPI_FILE"),
        help="Use local OpenAPI spec file instead of fetching from server",
    )
    parser.add_argument(
        "--use-included-api-spec",
        action="store_true",
        help="Use the OpenAPI spec bundled with this package instead of fetching from the cluster",
    )
    parser.add_argument(
        "--enable-daos",
        action="store_true",
        help="Enable DAOS-specific tools and endpoints (reduces tool count by ~30 when disabled)",
    )
    parser.add_argument(
        "--disable-specialty-features",
        action="store_true",
        help="Disable specialty features like rbd-mirror, qos-settings (further reduces tool count)",
    )
    args = parser.parse_args()

    server = CroitCephServer(
        mode=args.mode,
        resolve_references=args.resolve_references,
        offer_whole_spec=args.offer_whole_spec,
        max_category_tools=args.max_category_tools,
        openapi_file=args.openapi_file,
        use_included_api_spec=args.use_included_api_spec,
        enable_daos=args.enable_daos,
        enable_specialty_features=not args.disable_specialty_features,
    )
    # Set permission check flag
    server.check_permissions = args.check_permissions

    try:
        await server.run()
    finally:
        await server.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
