#!/usr/bin/env python3
"""
MCP Croit Ceph Extension
Dynamically loads swagger.json from croit.io host and generates tools
"""

import os
import json
import asyncio
import logging
from typing import Any, Dict, List, Optional
from pathlib import Path
import aiohttp
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.server.stdio
import mcp.types as types

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class CroitCephServer:
    def __init__(self):
        self.server = Server("mcp-croit-ceph")
        self.api_spec = None
        self.host = None
        self.api_token = None
        self.session = None
        
        # Register handlers
        self.server.list_tools()(self.handle_list_tools)
        self.server.call_tool()(self.handle_call_tool)
        self.server.list_resources()(self.handle_list_resources)
        self.server.read_resource()(self.handle_read_resource)
    
    async def load_config(self):
        """Load configuration from environment or file"""
        # First try environment variables
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
            logger.error("Missing CROIT_HOST or CROIT_API_TOKEN configuration")
            return
        
        # Ensure host doesn't have trailing slash
        self.host = self.host.rstrip("/")
        
        # Load swagger.json from host
        await self.fetch_swagger_spec()
    
    async def fetch_swagger_spec(self):
        """Fetch swagger.json from croit.io host"""
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        swagger_url = f"{self.host}/api/swagger.json"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json"
        }
        
        try:
            logger.info(f"Fetching swagger spec from {swagger_url}")
            async with self.session.get(swagger_url, headers=headers, ssl=False) as resp:
                if resp.status == 200:
                    # Get text first, then parse JSON manually
                    text = await resp.text()
                    self.api_spec = json.loads(text)
                    logger.info(f"Successfully loaded API spec with {len(self.api_spec.get('paths', {}))} endpoints")
                else:
                    error_text = await resp.text()
                    logger.error(f"Failed to fetch swagger spec: {resp.status} - {error_text}")
        except Exception as e:
            logger.error(f"Error fetching swagger spec: {e}")
    
    def parse_swagger_to_tools(self) -> List[types.Tool]:
        """Convert Swagger paths to MCP tools"""
        if not self.api_spec:
            return []
        
        tools = []
        paths = self.api_spec.get("paths", {})
        
        for path, methods in paths.items():
            for method, operation in methods.items():
                if method.lower() not in ["get", "post", "put", "delete", "patch"]:
                    continue
                
                # Skip if deprecated
                if operation.get("deprecated", False):
                    continue
                
                # Generate tool name from operationId or path
                operation_id = operation.get("operationId")
                if operation_id:
                    tool_name = operation_id.replace("-", "_").replace(" ", "_").lower()
                else:
                    # Fallback: create name from method and path
                    clean_path = path.replace("/", "_").replace("{", "").replace("}", "").strip("_")
                    tool_name = f"{method}_{clean_path}".lower()
                
                # Build description
                description = operation.get("summary", "")
                if operation.get("description"):
                    description = f"{description} - {operation['description']}" if description else operation["description"]
                if not description:
                    description = f"{method.upper()} {path}"
                
                # Build parameters schema
                parameters = self._build_parameters_schema(operation)
                
                tool = types.Tool(
                    name=tool_name,
                    description=description[:500],  # Limit description length
                    inputSchema=parameters
                )
                tools.append(tool)
        
        return tools
    
    def _build_parameters_schema(self, operation: Dict) -> Dict:
        """Build JSON schema for operation parameters"""
        schema = {
            "type": "object",
            "properties": {},
            "required": []
        }
        
        # Path, query, and header parameters
        for param in operation.get("parameters", []):
            param_name = param["name"]
            param_in = param["in"]
            
            if param_in in ["path", "query", "header"]:
                param_schema = param.get("schema", {})
                prop_schema = {
                    "type": param_schema.get("type", "string"),
                    "description": param.get("description", "")
                }
                
                # Add enum if present
                if "enum" in param_schema:
                    prop_schema["enum"] = param_schema["enum"]
                
                # Add format if present
                if "format" in param_schema:
                    prop_schema["format"] = param_schema["format"]
                
                schema["properties"][param_name] = prop_schema
                
                if param.get("required", False):
                    schema["required"].append(param_name)
        
        # Request body
        if "requestBody" in operation:
            content = operation["requestBody"].get("content", {})
            if "application/json" in content:
                body_schema = content["application/json"].get("schema", {})
                schema["properties"]["body"] = {
                    "type": "object",
                    "description": operation["requestBody"].get("description", "Request body"),
                    "additionalProperties": True  # Allow any properties
                }
                
                # Copy properties if they exist
                if "$ref" in body_schema:
                    # Handle reference to definition
                    ref_path = body_schema["$ref"].split("/")[-1]
                    if "definitions" in self.api_spec:
                        definition = self.api_spec["definitions"].get(ref_path, {})
                        if "properties" in definition:
                            schema["properties"]["body"]["properties"] = definition["properties"]
                            schema["properties"]["body"]["required"] = definition.get("required", [])
                elif "properties" in body_schema:
                    schema["properties"]["body"]["properties"] = body_schema["properties"]
                    schema["properties"]["body"]["required"] = body_schema.get("required", [])
                
                if operation["requestBody"].get("required", False):
                    schema["required"].append("body")
        
        return schema
    
    async def handle_list_tools(self) -> List[types.Tool]:
        """Return available tools based on Swagger spec"""
        if not self.api_spec:
            await self.load_config()
        
        tools = self.parse_swagger_to_tools()
        logger.info(f"Providing {len(tools)} tools")
        return tools
    
    async def handle_call_tool(self, name: str, arguments: Dict) -> List[types.TextContent]:
        """Execute API call based on tool name and arguments"""
        if not self.api_spec:
            return [types.TextContent(type="text", text="Swagger spec not loaded")]
        
        # Find operation details
        operation_details = self._find_operation_by_tool_name(name)
        if not operation_details:
            return [types.TextContent(type="text", text=f"Tool {name} not found")]
        
        path, method, operation = operation_details
        
        # Build request URL
        url = f"{self.host}/api{path}"
        
        # Build headers
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json"
        }
        
        # Determine content type
        if "requestBody" in operation:
            content = operation["requestBody"].get("content", {})
            if "application/json" in content:
                headers["Content-Type"] = "application/json"
        
        # Process parameters
        params = {}
        body = None
        path_params = {}
        
        # Separate body from other parameters
        if "body" in arguments:
            body = arguments["body"]
        
        # Process non-body parameters
        for key, value in arguments.items():
            if key == "body":
                continue
            
            # Find parameter definition
            param_def = None
            for p in operation.get("parameters", []):
                if p["name"] == key:
                    param_def = p
                    break
            
            if param_def:
                if param_def["in"] == "query":
                    # Handle array parameters for query
                    if param_def.get("schema", {}).get("type") == "array":
                        # Convert array to repeated query params
                        if isinstance(value, list):
                            params[key] = value
                        else:
                            params[key] = [value]
                    else:
                        params[key] = value
                elif param_def["in"] == "path":
                    path_params[key] = str(value)
                elif param_def["in"] == "header":
                    headers[key] = str(value)
        
        # Replace all path parameters
        for key, value in path_params.items():
            url = url.replace(f"{{{key}}}", value)
        
        # Make request
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        try:
            logger.info(f"Calling {method.upper()} {url}")
            if body:
                logger.debug(f"Request body: {json.dumps(body, indent=2)}")
            
            kwargs = {
                "headers": headers,
                "ssl": False  # For demo clusters
            }
            
            # Add query params if present
            if params:
                kwargs["params"] = params
            
            # Add body for appropriate methods
            if body is not None and method.upper() in ["POST", "PUT", "PATCH", "DELETE"]:
                kwargs["json"] = body
            
            async with self.session.request(method.upper(), url, **kwargs) as resp:
                # Get response text
                response_text = await resp.text()
                
                # Try to parse as JSON
                try:
                    response_data = json.loads(response_text) if response_text else None
                except:
                    response_data = response_text
                
                result = {
                    "status": resp.status,
                    "statusText": resp.reason,
                    "headers": dict(resp.headers),
                    "data": response_data
                }
                
                # Format response
                if resp.status >= 200 and resp.status < 300:
                    return [types.TextContent(
                        type="text",
                        text=json.dumps(result, indent=2)
                    )]
                else:
                    error_msg = f"API Error: {resp.status} {resp.reason}\n"
                    if response_data:
                        error_msg += json.dumps(response_data, indent=2)
                    return [types.TextContent(
                        type="text",
                        text=error_msg
                    )]
                    
        except Exception as e:
            logger.error(f"Request error: {e}")
            return [types.TextContent(
                type="text",
                text=f"Request failed: {str(e)}"
            )]
    
    def _find_operation_by_tool_name(self, tool_name: str) -> Optional[tuple]:
        """Find operation details by tool name"""
        paths = self.api_spec.get("paths", {})
        
        for path, methods in paths.items():
            for method, operation in methods.items():
                if method.lower() not in ["get", "post", "put", "delete", "patch"]:
                    continue
                
                # Generate tool name same way as in parse_swagger_to_tools
                operation_id = operation.get("operationId")
                if operation_id:
                    check_name = operation_id.replace("-", "_").replace(" ", "_").lower()
                else:
                    clean_path = path.replace("/", "_").replace("{", "").replace("}", "").strip("_")
                    check_name = f"{method}_{clean_path}".lower()
                
                if check_name == tool_name:
                    return (path, method, operation)
        
        return None
    
    async def handle_list_resources(self) -> List[types.Resource]:
        """Return available resources"""
        resources = []
        if self.api_spec:
            resources.append(types.Resource(
                uri=f"{self.host}/api/swagger.json",
                name="Croit API Specification",
                description="OpenAPI/Swagger specification for the Croit Ceph cluster",
                mimeType="application/json"
            ))
        return resources
    
    async def handle_read_resource(self, uri: str) -> str:
        """Read a resource by URI"""
        if uri == f"{self.host}/api/swagger.json" and self.api_spec:
            return json.dumps(self.api_spec, indent=2)
        return "Resource not found"
    
    async def run(self):
        """Run the MCP server"""
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await self.load_config()
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
                    instructions="This MCP server provides access to Croit Ceph cluster APIs. Tools are dynamically generated from the cluster's Swagger/OpenAPI specification."
                )
            )
    
    async def cleanup(self):
        """Cleanup resources"""
        if self.session:
            await self.session.close()

async def main():
    server = CroitCephServer()
    try:
        await server.run()
    finally:
        await server.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
