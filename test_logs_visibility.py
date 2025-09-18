#!/usr/bin/env python3
"""Test if logs endpoint is visible in MCP tools"""

import json
import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import using the script name
import importlib.util
spec = importlib.util.spec_from_file_location("mcp_module", "mcp-croit-ceph.py")
mcp_module = importlib.util.module_from_spec(spec)

# Mock the required modules
sys.modules['aiohttp'] = type(sys)('aiohttp')
sys.modules['mcp'] = type(sys)('mcp')
sys.modules['mcp.types'] = type(sys)('mcp.types')

# Create minimal mock classes
class MockTool:
    def __init__(self, name, description, inputSchema, outputSchema=None):
        self.name = name
        self.description = description
        self.inputSchema = inputSchema
        self.outputSchema = outputSchema

sys.modules['mcp'].types = type(sys)('types')
sys.modules['mcp'].types.Tool = MockTool

try:
    spec.loader.exec_module(mcp_module)
    CroitMcpServer = mcp_module.CroitMcpServer

    # Test different modes
    for mode in ['hybrid', 'base_only', 'categories_only', 'endpoints_as_tools']:
        print(f"\n=== Testing mode: {mode} ===")

        server = CroitMcpServer(
            mode=mode,
            openapi_file='openapi.json',
            no_permission_check=True,
            max_category_tools=10
        )

        # Check category analysis
        if hasattr(server, 'category_endpoints'):
            if 'logs' in server.category_endpoints:
                print(f"✅ 'logs' category found with {len(server.category_endpoints['logs'])} endpoints")
                for ep in server.category_endpoints['logs'][:3]:
                    print(f"   - {ep['method'].upper()} {ep['path']}")
            else:
                print("❌ 'logs' category NOT found in category_endpoints")
                print(f"   Available categories: {list(server.category_endpoints.keys())[:10]}...")

        # Check if logs tools are generated
        log_tools = [tool for tool in server.mcp_tools if 'log' in tool.name.lower()]
        if log_tools:
            print(f"✅ Found {len(log_tools)} log-related tools:")
            for tool in log_tools[:5]:
                print(f"   - {tool.name}")
                if 'export' in tool.name:
                    print(f"     Description: {tool.description[:200]}...")
        else:
            print("❌ No log-related tools found")

        # In hybrid/categories mode, check category tools
        if mode in ['hybrid', 'categories_only']:
            category_tools = [tool for tool in server.mcp_tools if 'manage_' in tool.name or 'logs' in tool.name]
            if category_tools:
                print(f"📦 Category tools that might handle logs:")
                for tool in category_tools:
                    if 'log' in tool.name.lower() or 'log' in tool.description.lower():
                        print(f"   - {tool.name}: {tool.description[:100]}...")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()