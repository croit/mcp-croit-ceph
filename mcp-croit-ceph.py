#!/usr/bin/env python3
"""
MCP Croit Ceph Server - Entry Point

This is the main entry point for the MCP Croit Ceph server.
All implementation logic is in the src/ directory.

Usage:
    python mcp-croit-ceph.py [options]

Environment Variables:
    CROIT_HOST       - Croit cluster URL (required)
    CROIT_API_TOKEN  - API token (required)
    LOG_LEVEL        - Logging level (optional, default: INFO)

For more options, run:
    python mcp-croit-ceph.py --help
"""

import sys
import asyncio

# Import the main server class from src
from src.core.mcp_server import main

if __name__ == "__main__":
    # Run the server
    asyncio.run(main())
