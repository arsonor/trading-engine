"""Alert-related MCP tools.

Tools:
- explain_alert: Detailed explanation of why an alert triggered
- list_alerts: List recent alerts with optional filters
- get_alert_by_id: Get specific alert details
- mark_alert_read: Mark an alert as read
- get_alert_statistics: Alert stats for performance tracking

Implementation: Phase 9.3
"""

# Tools will be implemented in Phase 9.3
# They will use decorators like:
#
# from app.mcp.server import mcp, get_db_session
#
# @mcp.tool()
# async def explain_alert(alert_id: int) -> str:
#     """Explain why an alert was triggered."""
#     async with get_db_session() as session:
#         ...
