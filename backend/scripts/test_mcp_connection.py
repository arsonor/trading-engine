#!/usr/bin/env python
"""Test script to verify MCP server can start and connect to database.

Usage:
    uv run python scripts/test_mcp_connection.py

This script verifies:
1. MCP dependencies are installed
2. Server can be instantiated
3. Database connection works
"""

import asyncio
import os
import sys

# Add the backend directory to Python path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

# Load environment variables
from dotenv import load_dotenv

load_dotenv(os.path.join(backend_dir, ".env"))


async def test_connection():
    """Test MCP server and database connection."""
    print("Testing MCP Server Setup...")
    print("=" * 50)

    # Test 1: Import MCP dependencies
    print("\n1. Testing MCP imports...")
    try:
        from mcp.server.fastmcp import FastMCP

        print("   [OK] mcp package imported successfully")
    except ImportError as e:
        print(f"   [FAIL] Cannot import mcp: {e}")
        print("   Run: uv sync")
        return False

    # Test 2: Import server module
    print("\n2. Testing server module...")
    try:
        from app.mcp.server import mcp, get_db_session
        from app.mcp.config import get_mcp_settings

        settings = get_mcp_settings()
        print(f"   [OK] Server name: {settings.server_name}")
        print(f"   [OK] Server version: {settings.server_version}")
    except ImportError as e:
        print(f"   [FAIL] Cannot import server: {e}")
        return False

    # Test 3: Database connection
    print("\n3. Testing database connection...")
    try:
        from app.mcp.server import get_db_session
        from sqlalchemy import text

        async with get_db_session() as session:
            result = await session.execute(text("SELECT 1"))
            result.scalar()
            print("   [OK] Database connection successful")
    except Exception as e:
        print(f"   [FAIL] Database connection failed: {e}")
        return False

    # Test 4: List registered tools
    print("\n4. Testing tool registration...")
    try:
        from app.mcp.server import mcp, ensure_tools_registered

        ensure_tools_registered()
        # FastMCP stores tools internally, so just check it doesn't error
        print("   [OK] Tool registration successful")
    except Exception as e:
        print(f"   [FAIL] Tool registration failed: {e}")
        return False

    print("\n" + "=" * 50)
    print("All tests passed! MCP server is ready.")
    return True


def main():
    """Run the tests."""
    success = asyncio.run(test_connection())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
