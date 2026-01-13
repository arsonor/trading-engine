"""MCP resources for read-only data access.

Resources:
- alerts://recent - Recent alerts
- alerts://unread - Unread alerts
- rules://active - Active rules configuration
- stats://daily - Daily statistics summary
- watchlist://current - Current watchlist

Implementation: Phase 9.7
"""

# Resources will be implemented in Phase 9.7
# They will use decorators like:
#
# from app.mcp.server import mcp, get_db_session
#
# @mcp.resource("alerts://recent")
# async def get_recent_alerts() -> str:
#     """Get recent alerts as a resource."""
#     async with get_db_session() as session:
#         ...
