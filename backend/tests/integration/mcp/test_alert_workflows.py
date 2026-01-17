"""Integration tests for MCP alert workflows.

These tests verify complete alert management workflows through MCP tools.
"""

import pytest


class TestAlertLifecycleWorkflow:
    """Test complete alert lifecycle through MCP tools."""

    @pytest.mark.asyncio
    async def test_list_and_explain_alert_flow(
        self, patch_all_mcp_modules, trading_alerts, trading_rules
    ):
        """Test listing alerts and getting detailed explanation."""
        from app.mcp.tools.alerts import explain_alert, list_alerts

        # First, list recent alerts
        list_result = await list_alerts(limit=5)

        assert "Recent Alerts" in list_result
        assert "NVDA" in list_result  # Most recent alert

        # Get the first alert ID and explain it
        # NVDA should be first (most recent)
        nvda_alert = next(a for a in trading_alerts if a.symbol == "NVDA")
        explain_result = await explain_alert(nvda_alert.id)

        assert f"Alert #{nvda_alert.id}" in explain_result
        assert "NVDA" in explain_result
        assert "BREAKOUT" in explain_result
        assert "Risk/Reward Ratio" in explain_result
        assert "High Volume Breakout" in explain_result  # Rule name

    @pytest.mark.asyncio
    async def test_filter_and_mark_read_flow(
        self, patch_all_mcp_modules, trading_alerts
    ):
        """Test filtering unread alerts and marking them as read."""
        from app.mcp.tools.alerts import list_alerts, mark_alert_read

        # List unread alerts
        unread_result = await list_alerts(unread_only=True)

        assert "Recent Alerts" in unread_result
        # Should have 3 unread alerts (NVDA, AMD, SMCI)
        assert "3 shown" in unread_result

        # Mark the first unread alert as read
        nvda_alert = next(a for a in trading_alerts if a.symbol == "NVDA")
        mark_result = await mark_alert_read(nvda_alert.id)

        assert "marked as read" in mark_result.lower()
        assert "NVDA" in mark_result

        # Verify it's no longer in unread list
        unread_after = await list_alerts(unread_only=True)
        assert "2 shown" in unread_after

    @pytest.mark.asyncio
    async def test_filter_by_symbol_and_type(
        self, patch_all_mcp_modules, trading_alerts
    ):
        """Test filtering alerts by symbol and setup type."""
        from app.mcp.tools.alerts import list_alerts

        # Filter by symbol
        nvda_result = await list_alerts(symbol="NVDA")
        assert "NVDA" in nvda_result
        assert "AMD" not in nvda_result or "symbol=NVDA" in nvda_result

        # Filter by setup type
        breakout_result = await list_alerts(setup_type="breakout")
        assert "BREAKOUT" in breakout_result

        # Combined filter
        combined = await list_alerts(symbol="NVDA", setup_type="breakout")
        assert "NVDA" in combined
        assert "BREAKOUT" in combined

    @pytest.mark.asyncio
    async def test_statistics_workflow(
        self, patch_all_mcp_modules, trading_alerts, trading_rules
    ):
        """Test getting and analyzing alert statistics."""
        from app.mcp.tools.alerts import get_alert_statistics

        # Get 7-day statistics
        stats_7d = await get_alert_statistics(days=7)

        assert "Alert Statistics" in stats_7d
        assert "7 Days" in stats_7d
        assert "Total Alerts" in stats_7d
        assert "By Setup Type" in stats_7d
        assert "BREAKOUT" in stats_7d
        assert "Top Symbols" in stats_7d
        assert "NVDA" in stats_7d  # Should be in top symbols

        # Get 30-day statistics
        stats_30d = await get_alert_statistics(days=30)
        assert "30 Days" in stats_30d

    @pytest.mark.asyncio
    async def test_get_alert_details_flow(
        self, patch_all_mcp_modules, trading_alerts, trading_rules
    ):
        """Test getting detailed information about specific alerts."""
        from app.mcp.tools.alerts import get_alert_by_id

        # Get details for high-confidence alert
        nvda_alert = next(a for a in trading_alerts if a.symbol == "NVDA")
        result = await get_alert_by_id(nvda_alert.id)

        assert f"Alert #{nvda_alert.id}" in result
        assert "NVDA" in result
        assert "Price Levels" in result
        assert "Entry Price" in result
        assert "Stop Loss" in result
        assert "Target Price" in result
        assert "Rule" in result
        assert "High Volume Breakout" in result


class TestAlertResourcesIntegration:
    """Test MCP resources for alerts."""

    @pytest.mark.asyncio
    async def test_recent_alerts_resource(
        self, patch_all_mcp_modules, trading_alerts
    ):
        """Test alerts://recent resource returns properly formatted data."""
        from app.mcp.resources.data import get_recent_alerts

        result = await get_recent_alerts()

        assert "Recent Alerts" in result
        assert "Last 20" in result
        assert "[UNREAD]" in result  # Should have unread alerts
        assert "NVDA" in result  # Most recent

    @pytest.mark.asyncio
    async def test_unread_alerts_resource(
        self, patch_all_mcp_modules, trading_alerts
    ):
        """Test alerts://unread resource."""
        from app.mcp.resources.data import get_unread_alerts

        result = await get_unread_alerts()

        assert "Unread Alerts" in result
        assert "3" in result  # Should have 3 unread
        # All unread should be listed
        assert "NVDA" in result
        assert "AMD" in result
        assert "SMCI" in result

    @pytest.mark.asyncio
    async def test_daily_stats_resource(
        self, patch_all_mcp_modules, trading_alerts, trading_rules, watchlist
    ):
        """Test stats://daily resource."""
        from app.mcp.resources.data import get_daily_stats

        result = await get_daily_stats()

        assert "Daily Statistics" in result
        assert "ALERTS" in result
        assert "Today:" in result
        assert "Unread:" in result
        assert "Active Rules:" in result
        assert "Watchlist:" in result
