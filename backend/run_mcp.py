#!/usr/bin/env python
"""Standalone MCP server entry point.

This script sets up the Python path correctly before running the MCP server,
making it work regardless of what working directory it's called from.

Usage in Claude Desktop config:
{
  "mcpServers": {
    "trading-engine": {
      "command": "uv",
      "args": ["run", "G:/Users/Martin/GITHUB/trading-engine/backend/run_mcp.py"]
    }
  }
}
"""

import os
import sys

# Get the directory where this script lives (backend folder)
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))

# Add backend to Python path so 'app' module can be found
sys.path.insert(0, BACKEND_DIR)

# Change to backend directory
os.chdir(BACKEND_DIR)

# Now import and run the MCP server
from app.mcp.server import main

if __name__ == "__main__":
    main()
