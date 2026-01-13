#!/usr/bin/env python
"""Run the Trading Engine MCP server for development/testing.

Usage:
    # From the backend directory:
    uv run python scripts/run_mcp_server.py

    # Or run the module directly:
    uv run python -m app.mcp.server

This script is a convenience wrapper that ensures proper environment setup.
"""

import os
import sys

# Add the backend directory to Python path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

# Load environment variables from .env if present
from dotenv import load_dotenv

load_dotenv(os.path.join(backend_dir, ".env"))


def main():
    """Run the MCP server."""
    print("Starting Trading Engine MCP Server...", file=sys.stderr)
    print(f"Database URL: {os.getenv('DATABASE_URL', 'not set')}", file=sys.stderr)
    print("", file=sys.stderr)

    from app.mcp.server import main as mcp_main

    mcp_main()


if __name__ == "__main__":
    main()
