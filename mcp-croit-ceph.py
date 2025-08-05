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
        endpoints_as_tools=False,
        resolve_references=True,
        offer_whole_spec=False,
    ):
        self.tools: Dict[str, CroitToolInfo] = {}
        self.mcp_tools: List[types.Tool] = []
        self.api_spec = None
        self.host = None
        self.resolved_references = False
        self._load_config()
        self._fetch_swagger_spec()
        self.session = aiohttp.ClientSession()

        if resolve_references:
            self._resolve_swagger_references()

        if endpoints_as_tools:
            self._parse_swagger_to_tools()
            tool_handler = self.handle_call_tool
            self.instructions = (
                "This MCP server provides access to a croit Ceph cluster."
            )
        else:
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
        """Load configuration from environment or file"""
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

    def _fetch_swagger_spec(self):
        """Fetch swagger.json from croit.io host"""
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
        """Rsesolve a $ref reference in the swagger specification."""
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
        """Recursively resolve all $ref references in the swagger specification."""

        # To fix the recursion in our PaginationRequest, we add it via $defs.
        # See https://www.stainless.com/blog/lessons-from-openapi-to-mcp-server-conversion
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
            """Recursively resolve references in an object"""
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

    def _parse_swagger_to_tools(self):
        """Convert Swagger paths to MCP tools"""

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
                description = description[:500]

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
        """Extract input parameters for tools from OpenAPI spec"""
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
        """Build JSON schema for operation response"""

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
        """Convert OpenAPI schema to JSON schema format"""
        # https://spec.openapis.org/oas/v3.1.0.html#schema-object
        # The Schema Object format from OpenAPI is a superset JSON schema.
        # It doesn't add a lot, so we just use it directly and hope it works.
        schema = openapi_schema.get("schema", {}).copy()
        # The description tends to be outside of the OpenAPI schema in a description field.
        if schema.get("description", "") == "":
            schema["description"] = openapi_schema.get("description", "")
        return schema

    def _prepare_api_tools(self):
        """Convert Swagger paths to MCP tools"""

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
                            "type": "string",
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
        """Return available tools based on Swagger spec"""
        logger.info(f"Providing {len(self.mcp_tools)} tools")
        return self.mcp_tools

    async def handle_call_tool(
        self,
        name: str,
        arguments: Dict,
    ) -> dict[str, Any]:
        """Execute API call based on tool name and arguments"""
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
        """Construct the URL from the arguments provided by the LLM"""
        url = f"{self.host}/api{tool.path}"

        for key, value in arguments.items():
            if key != "body" and key in tool.path_params:
                url = url.replace(f"{{{key}}}", str(value))
        return url

    def _make_query_params(self, tool: CroitToolInfo, arguments: Dict) -> str:
        """Construct a query parameter dict from the arguments provided by the LLM"""
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
        """Handle the tools to let the LLM inspect and call the croit API directly"""
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
        """Run the MCP server"""
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

    async def cleanup(self):
        """Cleanup resources"""
        if self.session:
            await self.session.close()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--endpoints-as-tools",
        action="store_true",
        help="Map each API endpoint to a separate MCP tool.",
    )
    parser.add_argument(
        "--no-resolve-references",
        action="store_false",
        help="Don't resolve $refs in the API spec. Depending on the MCP client, resolving references may be required.",
    )
    parser.add_argument(
        "--offer-whole-spec",
        action="store_true",
        help="Offer the entire API spec in the list_api_endpoints tool. Ignored when setting --endpoints-as-tools.",
    )
    args = parser.parse_args()

    server = CroitCephServer(
        endpoints_as_tools=args.endpoints_as_tools,
        resolve_references=not args.no_resolve_references,
        offer_whole_spec=args.offer_whole_spec,
    )
    try:
        await server.run()
    finally:
        await server.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
