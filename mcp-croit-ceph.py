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


@dataclass
class QueryParamInfo:
    is_array: bool
    required: bool


@dataclass
class CroitToolInfo:
    path: str
    method: str
    expects_body: bool
    path_params: List[str]
    query_params: Dict[str, QueryParamInfo]


@dataclass
class ToolParameters:
    input_schema: Dict
    expects_body: bool
    path_params: List[str]
    query_params: Dict[str, QueryParamInfo]


class CroitCephServer:
    def __init__(
        self,
        mode="hybrid",  # New mode parameter: "hybrid", "base_only", "categories_only", "endpoints_as_tools"
        resolve_references=True,
        offer_whole_spec=False,
        endpoints_as_tools=False,  # Kept for backwards compatibility
        max_category_tools=40,  # Maximum number of category tools to generate (40 covers all current categories)
        min_endpoints_per_category=1,  # Minimum endpoints needed for a category tool (include single-endpoint categories like logs)
        openapi_file=None,  # Optional: Use local OpenAPI spec file instead of fetching from server
    ):
        # tools is a map of tool name (as given to and later provided by the LLM) to the tool info.
        # Each endpoint is represented in this map as a tool.
        # Only used if endpoints_as_tools is True, as we don't map endpoints otherwise.
        self.tools: Dict[str, CroitToolInfo] = {}
        # mcp_tools later contains the list of tools that will be advertised to the LLM.
        # The exact list depends on mode.
        self.mcp_tools: List[types.Tool] = []
        # api_spec contains the OpenAPI schema as returned from the cluster.
        self.api_spec = None
        # host is the cluster URL, e.g. http://172.31.134.4:8080.
        self.host = None
        # resolved_references will later be set to true when resolve_references is True.
        # Meaning if True, the spec won't contain any $ref references anymore.
        self.resolved_references = False
        # Category mapping for hybrid mode
        self.category_endpoints = {}
        # session is later used to make the actual API calls to the cluster.
        self.session = aiohttp.ClientSession()

        # Handle backwards compatibility
        if endpoints_as_tools:
            mode = "endpoints_as_tools"
        self.mode = mode
        self.max_category_tools = max_category_tools
        self.min_endpoints_per_category = min_endpoints_per_category
        self.openapi_file = openapi_file

        self._load_config()
        if openapi_file:
            self._load_local_swagger_spec()
        else:
            self._fetch_swagger_spec()

        if resolve_references:
            self._resolve_swagger_references()

        # Configure based on mode
        if mode == "endpoints_as_tools":
            self._convert_endpoints_to_tools()
            tool_handler = self.handle_call_tool
            self.instructions = (
                "This MCP server provides access to a croit Ceph cluster."
            )
        elif mode == "hybrid":
            self.offer_whole_spec = offer_whole_spec
            self._analyze_api_structure()
            self._prepare_hybrid_tools()
            tool_handler = self.handle_hybrid_tool
            self.instructions = """This MCP server provides access to a croit Ceph cluster.

Available tools:
- list_endpoints: List API endpoints with filtering options
- call_endpoint: Call any API endpoint directly
- Category-specific tools for common operations (e.g., manage_services, manage_pools)

Use category tools for common operations, or use list_endpoints/call_endpoint for any endpoint."""
        elif mode == "categories_only":
            self._analyze_api_structure()
            self._prepare_category_tools_only()
            tool_handler = self.handle_category_tool
            self.instructions = """This MCP server provides access to a croit Ceph cluster.

Category-based tools are available for common operations like managing services, pools, and storage."""
        else:  # base_only (default fallback)
            self.offer_whole_spec = offer_whole_spec
            self._prepare_api_tools()
            tool_handler = self.handle_api_call_tool
            self.instructions = """This MCP server provides access to a croit Ceph cluster.
Use list_api_endpoints to get an overview of what endpoints are available.
Use get_reference_schema to get more info on the schema for endpoints.
Use call_api_endpoint to then call one of the endpoints.
Many endpoints offer pagination. When available, use it to refine the query.
                    """

        self.server = Server("mcp-croit-ceph")
        # These functions create decorators to register the handlers.
        # We then call the decorator with our functions.
        # We can't use the decorators directly because of self.
        self.server.list_tools()(self.handle_list_tools)
        self.server.call_tool()(tool_handler)

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
            with open(self.openapi_file, 'r') as f:
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

    def _convert_endpoints_to_tools(self):
        """
        Turn each endpoint in self.api_spec into a MCP tool.
        Will populate self.tools with a map of tool name to the tool information for each endpoint,
        and self.mcp_tools with a list of all tools.
        Meaning both will contain as many elements as there are API endpoints (plus some extra non-API tools).
        """

        self.tools = {}
        paths = self.api_spec.get("paths", {})
        for path, methods in paths.items():
            for method, operation in methods.items():
                if method.lower() not in ["get", "post", "put", "delete", "patch"]:
                    continue

                if operation.get("deprecated", False):
                    continue

                operation_id = operation.get("operationId")
                if operation_id:
                    tool_name = operation_id.replace("-", "_").replace(" ", "_").lower()
                else:
                    logger.error(
                        f"API endpoint {path} does not have an operation ID defined"
                    )
                    continue

                description = operation.get("summary", "")
                if operation.get("description"):
                    description = (
                        f"{description} - {operation['description']}"
                        if description
                        else operation["description"]
                    )
                if not description:
                    description = f"{method.upper()} {path}"

                # Add examples from x-llm-hints if available
                llm_hints = operation.get("x-llm-hints", {})
                if "request_examples" in llm_hints:
                    examples = llm_hints["request_examples"]
                    if examples:
                        description += "\n\nExample request:"
                        # Take first example for brevity
                        example = examples[0] if isinstance(examples, list) else examples
                        if isinstance(example, dict) and "example" in example:
                            import json
                            description += f"\n```json\n{json.dumps(example['example'], indent=2)}\n```"
                        elif isinstance(example, str):
                            description += f"\n```json\n{example}\n```"

                # Add parameter details if available
                if "parameter_details" in llm_hints:
                    description += "\n\nParameter details:"
                    for param, detail in llm_hints["parameter_details"].items():
                        description += f"\n- {param}: {detail}"

                # Add token optimization hints for large data endpoints
                if any(pattern in path.lower() for pattern in ['/list', '/all', '/export', '/stats', '/logs']):
                    description += "\n\n💡 Token Optimization:"
                    description += "\n• Use limit=10 for initial exploration"
                    description += "\n• Add filters to reduce data (e.g. status='error')"
                    description += "\n• Large responses will be auto-truncated to 50 items"

                description = description[:1200]  # Increased limit for examples and hints

                parameters = self._build_parameters_schema(operation)
                # Specifying the output schema means it must be correct.
                # This can fail tool calls for no reason, so I disabled the output schema for now.
                # response_schema = self._build_response_schema(operation)

                tool = types.Tool(
                    name=tool_name,
                    description=description,
                    inputSchema=parameters.input_schema,
                    # outputSchema=response_schema,
                )
                self.mcp_tools.append(tool)
                self.tools[tool_name] = CroitToolInfo(
                    path=path,
                    method=method,
                    expects_body=parameters.expects_body,
                    path_params=parameters.path_params,
                    query_params=parameters.query_params,
                )
                logger.debug(f"Adding tool {tool_name}")

        logger.info(
            f"Successfully loaded API spec with {len(self.mcp_tools)} endpoints"
        )

        self.resolve_references_tool = "get_reference_schema"
        if self.resolve_references_tool in self.tools:
            raise RuntimeError(
                f"Tool {self.resolve_references_tool} is also defined as an API endpoint, this is unexpected"
            )
        # We only offer the tool if references haven't been resolved.
        if not self.resolved_references:
            self.mcp_tools.insert(
                0,
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
            )

    def _build_parameters_schema(self, operation: Dict) -> ToolParameters:
        """
        Given the OpenAPI spec of a single endpoint (including HTTP method), this will generate the ToolParameters.
        The ToolParameters describe the input schema for the tool, i.e. what request body and what path and query parameters are expected.
        """
        schema = {"type": "object", "properties": {}, "required": []}
        path_params: List[str] = []
        query_params: Dict[str, QueryParamInfo] = {}

        # Path and query parameters, see https://spec.openapis.org/oas/v3.1.0.html#parameter-object
        for param in operation.get("parameters", []):
            param_name = param["name"]
            param_location = param["in"]

            if param_location in ["path", "query"]:
                param_schema = self._convert_openapi_schema_to_json_schema(param)
                schema["properties"][param_name] = param_schema
                required = param.get("required", False)
                if required or param_location == "path":
                    schema["required"].append(param_name)
                if param_location == "query":
                    is_array = param_schema.get("type", "") == "array"
                    query_params[param_name] = QueryParamInfo(
                        required=required,
                        is_array=is_array,
                    )
                else:
                    path_params.append(param_name)

        # Request body, see https://spec.openapis.org/oas/v3.1.0.html#request-body-object
        expects_body = False
        if "requestBody" in operation:
            content = operation["requestBody"].get("content", {})
            if "application/json" in content:
                body_schema = self._convert_openapi_schema_to_json_schema(
                    content["application/json"]
                )
                schema["properties"]["body"] = body_schema
                if operation["requestBody"].get("required", False):
                    schema["required"].append("body")
                expects_body = True

        return ToolParameters(
            input_schema=schema,
            expects_body=expects_body,
            path_params=path_params,
            query_params=query_params,
        )

    def _build_response_schema(self, operation: Dict) -> Optional[Dict]:
        """
        Same as _build_parameters_schema, but for the response.
        We additionally wrap the response in our own object, that also includes the HTTP return code and error information.
        """

        schema = {
            "type": "object",
            "description": "Response from croit, with either an error string if failed or a result if successful",
            "properties": {
                "code": {
                    "type": "integer",
                    "format": "int32",
                    "description": "HTTP return code from croit",
                },
                "error": {
                    "type": "string",
                    "description": "Error message from croit (only if return code is an error code)",
                },
            },
            "required": ["code"],
        }

        # Response body, see https://spec.openapis.org/oas/v3.1.0.html#response-object
        content = operation.get("responses", {}).get("default", {}).get("content", {})
        if "application/json" not in content:
            return None

        body_schema = self._convert_openapi_schema_to_json_schema(
            content["application/json"]
        )
        schema["properties"]["result"] = body_schema
        return schema

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

    def _resolve_refs_in_schema(self, schema: Dict, depth: int = 0, seen_refs: set = None) -> Dict:
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
                resolved_props[prop_name] = self._resolve_refs_in_schema(prop_schema, depth + 1, seen_refs.copy())
            schema = schema.copy()
            schema["properties"] = resolved_props

        if "items" in schema:
            schema = schema.copy()
            schema["items"] = self._resolve_refs_in_schema(schema["items"], depth + 1, seen_refs.copy())

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

        # Sort categories by operation count and select top categories
        potential_categories = [
            cat for cat, count in tag_counter.most_common(self.max_category_tools * 2)  # Get more initially
            if count >= self.min_endpoints_per_category
        ]

        # Test permissions for each category if enabled
        if getattr(self, 'check_permissions', True):
            self.top_categories = self._filter_categories_by_permission(potential_categories)
        else:
            self.top_categories = potential_categories[:self.max_category_tools]

        logger.info(f"Found {len(tag_counter)} categories, selected {len(self.top_categories)} accessible: {self.top_categories}")

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

            resp = requests.get(token_info_url, headers=headers, verify=self.ssl, timeout=5)

            if resp.status_code == 200:
                data = resp.json()
                roles = data.get("roles", [])
                logger.info(f"User roles detected: {roles}")
                return roles if roles else ["VIEWER"]  # Default to VIEWER if empty (shouldn't happen)
            elif resp.status_code == 401:
                logger.error("Invalid API token - authentication failed")
                raise RuntimeError("Invalid API token. Please check your CROIT_API_TOKEN.")
            else:
                logger.error(f"Unexpected response from token-info: {resp.status_code}")
                raise RuntimeError(f"Failed to verify API token: HTTP {resp.status_code}")

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
            return categories[:self.max_category_tools]

        # Categories that require ADMIN role for write operations
        admin_only_categories = {
            'maintenance',  # System maintenance operations
            'servers',      # Server management
            'ipmi',         # IPMI/hardware control
            'config',       # Configuration changes
            'hooks',        # System hooks
            'change-requests',  # Change management
            'config-templates', # Configuration templates
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

        # Base tool: list_endpoints with filtering
        self.mcp_tools.append(types.Tool(
            name=self.list_endpoints_tool,
            description="List available API endpoints with filtering options",
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": f"Filter by category/tag. Available: {', '.join(self.top_categories[:10])}"
                    },
                    "method": {
                        "type": "string",
                        "enum": ["get", "post", "put", "delete", "patch"],
                        "description": "Filter by HTTP method"
                    },
                    "search": {
                        "type": "string",
                        "description": "Search term to filter endpoints by path or summary"
                    }
                }
            }
        ))

        # Base tool: call_endpoint
        self.mcp_tools.append(types.Tool(
            name=self.call_endpoint_tool,
            description="Call any API endpoint directly",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "API endpoint path (e.g., /services/{id})"
                    },
                    "method": {
                        "type": "string",
                        "enum": ["get", "post", "put", "delete", "patch"],
                        "description": "HTTP method"
                    },
                    "path_params": {
                        "type": "object",
                        "description": "Path parameters as key-value pairs"
                    },
                    "query_params": {
                        "type": "object",
                        "description": "Query parameters as key-value pairs"
                    },
                    "body": {
                        "type": "object",
                        "description": "Request body (for POST, PUT, PATCH)"
                    }
                },
                "required": ["path", "method"]
            }
        ))

        # Only add get_schema tool if references aren't resolved
        if not self.resolved_references:
            self.mcp_tools.append(types.Tool(
                name=self.get_schema_tool,
                description="Get schema definition for $ref references",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "reference": {
                            "type": "string",
                            "description": "Schema reference (e.g., #/components/schemas/Service)"
                        }
                    },
                    "required": ["reference"]
                }
            ))

        # Generate category tools for top categories
        for category in self.top_categories:
            self._generate_category_tool(category)

        logger.info(f"Generated {len(self.mcp_tools)} tools total (hybrid mode)")

    def _generate_category_tool(self, category: str):
        """
        Generate a category-specific tool for a given tag/category.
        """
        endpoints = self.category_endpoints.get(category, [])
        if not endpoints:
            return

        # Analyze available operations
        methods = set(ep["method"] for ep in endpoints)
        has_list = any(ep["method"] == "get" and "{" not in ep["path"] for ep in endpoints)
        has_get = any(ep["method"] == "get" and "{" in ep["path"] for ep in endpoints)
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
        description = f"Manage {category} resources. Available actions: {', '.join(actions)}"

        # Extract key LLM hints for tool description
        # Prioritize purpose and usage as they're most helpful for tool discovery
        hint_purposes = []
        hint_usages = []
        has_confirmations = False

        for ep in endpoints[:5]:  # Sample first 5 endpoints for hints
            hints = ep.get("llm_hints", {})
            if hints:
                # Collect purposes and usages for the description
                if hints.get("purpose") and len(hint_purposes) < 2:
                    hint_purposes.append(hints["purpose"][:100])
                if hints.get("usage") and len(hint_usages) < 3:
                    for usage in hints["usage"][:2]:
                        if len(hint_usages) < 3:
                            hint_usages.append(usage[:80])
                if hints.get("requires_confirmation"):
                    has_confirmations = True

        # Build enhanced description with hints
        if hint_purposes:
            description += f". Purpose: {hint_purposes[0]}"
        if hint_usages:
            description += f". Common usage: {hint_usages[0]}"
        if has_confirmations:
            description += ". Note: Some operations require confirmation"

        # Add examples from endpoint summaries
        example_ops = endpoints[:3]
        if example_ops:
            examples = [f"{ep['method'].upper()} {ep['path']}: {ep['summary']}" for ep in example_ops if ep['summary']]
            if examples:
                description += f". Examples: {'; '.join(examples[:2])}"

        input_schema = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": actions,
                    "description": f"Action to perform on {category}"
                },
                "resource_id": {
                    "type": "string",
                    "description": f"ID of the {category} resource (for get, update, delete)"
                },
                "filters": {
                    "type": "object",
                    "description": "Filters for list action (query parameters)"
                },
                "data": {
                    "type": "object",
                    "description": "Data for create or update actions"
                }
            },
            "required": ["action"]
        }

        self.mcp_tools.append(types.Tool(
            name=tool_name,
            description=description[:500],  # Limit description length
            inputSchema=input_schema
        ))

    def _prepare_category_tools_only(self):
        """
        Prepare only category-based tools (no base tools).
        """
        for category in self.top_categories:
            self._generate_category_tool(category)

        logger.info(f"Generated {len(self.mcp_tools)} category tools (categories_only mode)")

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

    async def handle_list_tools(self) -> List[types.Tool]:
        """Return available tools."""
        logger.info(f"Providing {len(self.mcp_tools)} tools")
        return self.mcp_tools

    async def handle_call_tool(
        self,
        name: str,
        arguments: Dict,
    ) -> dict[str, Any]:
        """
        Execute API call based on tool name and arguments.
        Each tool is mapped to a specific API endpoint.
        """
        logger.info(f"Tool call {name} with args {arguments}")
        if name == self.resolve_references_tool:
            resolved = self._resolve_reference_schema(
                ref_path=arguments["reference_path"]
            )
            return resolved

        if name not in self.tools:
            raise RuntimeError(f"Tool {name} not found")
        tool = self.tools[name]

        url = self._make_request_url(tool, arguments)
        query_params = self._make_query_params(tool, arguments)

        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
        }
        body = None
        if tool.expects_body:
            headers["Content-Type"] = "application/json"
            body = arguments["body"]

        kwargs = {"headers": headers, "ssl": self.ssl}
        if query_params:
            kwargs["params"] = query_params
        if tool.expects_body:
            kwargs["json"] = body

        return await self._make_api_call(url=url, method=tool.method, kwargs=kwargs)

    async def _make_api_call(
        self,
        url: str,
        method: str,
        kwargs: Dict,
    ) -> dict[str, Any]:
        """
        Helper function to make the actual API call.
        This function is async, make sure to call it with await before returning the result.
        """
        logger.info(f"Calling {method} {url}")
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"kwargs: {json.dumps(kwargs, indent=2)}")
        try:
            async with self.session.request(method.upper(), url, **kwargs) as resp:
                response_text = await resp.text()
                try:
                    response_data = json.loads(response_text) if response_text else None
                except:
                    response_data = response_text

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

    def _make_request_url(self, tool: CroitToolInfo, arguments: Dict) -> str:
        """Construct the URL from the arguments (i.e. path parameters) provided by the LLM."""
        url = f"{self.host}/api{tool.path}"

        for key, value in arguments.items():
            if key != "body" and key in tool.path_params:
                url = url.replace(f"{{{key}}}", str(value))
        return url

    def _make_query_params(self, tool: CroitToolInfo, arguments: Dict) -> str:
        """Construct a query parameter dict from the arguments provided by the LLM."""
        params = {}
        for key, value in arguments.items():
            if key == "body" or key not in tool.query_params:
                continue

            if isinstance(value, dict):
                value = json.dumps(value)

            param_def = tool.query_params[key]
            if param_def.is_array:
                # Convert array to repeated query params
                if isinstance(value, list):
                    params[key] = value
                else:
                    params[key] = [value]
            else:
                params[key] = value
        return params

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

        # Handle base tools
        if name == self.list_endpoints_tool:
            return self._list_endpoints_filtered(arguments)

        if name == self.call_endpoint_tool:
            return await self._call_endpoint_direct(arguments)

        if hasattr(self, 'get_schema_tool') and name == self.get_schema_tool:
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

        if name.startswith("manage_"):
            return await self._handle_category_tool(name, arguments)

        raise RuntimeError(f"Unknown tool: {name}")

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
                target_endpoint = ep
                break
            elif action == "create" and method == "post" and "{" not in path:
                target_endpoint = ep
                break
            elif action == "update" and method in ["put", "patch"] and "{" in path and resource_id:
                target_endpoint = ep
                break
            elif action == "delete" and method == "delete" and "{" in path and resource_id:
                target_endpoint = ep
                break

        if not target_endpoint:
            return {"error": f"No endpoint found for action '{action}' in category '{category}'"}

        # Build the request
        path = target_endpoint["path"]
        method = target_endpoint["method"]

        # Replace path parameters
        if resource_id and "{" in path:
            # Find parameter name (e.g., {id}, {name}, etc.)
            import re
            params = re.findall(r'\{([^}]+)\}', path)
            if params:
                path = path.replace(f"{{{params[0]}}}", str(resource_id))

        # Make the API call
        url = f"{self.host}/api{path}"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
        }

        kwargs = {"headers": headers, "ssl": self.ssl}

        if action == "list" and filters:
            kwargs["params"] = filters
        elif action in ["create", "update"] and data:
            headers["Content-Type"] = "application/json"
            kwargs["json"] = data

        result = await self._make_api_call(url=url, method=method, kwargs=kwargs)

        # Add context about the operation and LLM hints
        context = {
            "category": category,
            "action": action,
            "endpoint": path,
            "method": method.upper()
        }

        # Include ALL LLM hints if available - let the AI use what it needs
        if target_endpoint.get("llm_hints"):
            context["llm_hints"] = target_endpoint["llm_hints"]

        result["_operation"] = context

        return result

    def _list_endpoints_filtered(self, arguments: Dict) -> dict[str, Any]:
        """
        List API endpoints with optional filtering.
        """
        category_filter = arguments.get("category")
        method_filter = arguments.get("method")
        search_term = arguments.get("search", "").lower()

        results = []

        for path, methods in self.api_spec.get("paths", {}).items():
            for method, operation in methods.items():
                if method.lower() not in ["get", "post", "put", "delete", "patch"]:
                    continue

                # Apply filters
                if method_filter and method.lower() != method_filter.lower():
                    continue

                tags = operation.get("tags", [])
                if category_filter and category_filter not in tags:
                    continue

                summary = operation.get("summary", "")
                if search_term and search_term not in path.lower() and search_term not in summary.lower():
                    continue

                # Extract key LLM hints
                llm_hints = operation.get("x-llm-hints", {})
                endpoint_data = {
                    "path": path,
                    "method": method.upper(),
                    "operationId": operation.get("operationId", ""),
                    "summary": summary,
                    "tags": tags,
                    "deprecated": operation.get("deprecated", False)
                }

                # Add ALL LLM hints if present - let the AI decide what's important
                if llm_hints:
                    endpoint_data["llm_hints"] = llm_hints

                results.append(endpoint_data)

        return {
            "total": len(results),
            "endpoints": results[:100],  # Limit to prevent huge responses
            "truncated": len(results) > 100
        }

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

        url = f"{self.host}/api{path}"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
        }

        kwargs = {"headers": headers, "ssl": self.ssl}

        if query_params:
            kwargs["params"] = query_params

        if body and method in ["post", "put", "patch"]:
            headers["Content-Type"] = "application/json"
            kwargs["json"] = body

        return await self._make_api_call(url=url, method=method, kwargs=kwargs)

    async def cleanup(self):
        """Cleanup resources."""
        if self.session:
            await self.session.close()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["hybrid", "base_only", "categories_only", "endpoints_as_tools"],
        default="hybrid",
        help="Tool generation mode (default: hybrid)",
    )
    parser.add_argument(
        "--endpoints-as-tools",
        action="store_true",
        help="Legacy: Map each API endpoint to a separate MCP tool (same as --mode endpoints_as_tools)",
    )
    parser.add_argument(
        "--no-resolve-references",
        action="store_false",
        dest="resolve_references",
        help="Don't resolve $refs in the API spec. Depending on the MCP client, resolving references may be required.",
    )
    parser.add_argument(
        "--offer-whole-spec",
        action="store_true",
        help="Offer the entire API spec in the list_api_endpoints tool. Ignored when using --endpoints-as-tools.",
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
        help="Use local OpenAPI spec file instead of fetching from server",
    )
    args = parser.parse_args()

    # Handle legacy --endpoints-as-tools flag
    if args.endpoints_as_tools:
        mode = "endpoints_as_tools"
    else:
        mode = args.mode

    server = CroitCephServer(
        mode=mode,
        resolve_references=args.resolve_references,
        offer_whole_spec=args.offer_whole_spec,
        max_category_tools=args.max_category_tools,
        openapi_file=args.openapi_file,
    )
    # Set permission check flag
    server.check_permissions = args.check_permissions

    try:
        await server.run()
    finally:
        await server.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
