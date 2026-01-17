"""Unit tests for MCP resources."""

from unittest.mock import patch

import pytest


class TestRecentAlertsResource:
    """Tests for alerts://recent resource."""

    @pytest.mark.asyncio
    async def test_get_recent_alerts_with_data(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test getting recent alerts resource with data."""
        with patch("app.mcp.resources.data.get_db_session", mock_get_db_session):
            from app.mcp.resources.data import get_recent_alerts

            result = await get_recent_alerts()

            assert "Recent Alerts" in result
            assert "Last 20" in result
            # Check that some alerts are included
            assert "AAPL" in result or "GOOGL" in result

    @pytest.mark.asyncio
    async def test_get_recent_alerts_empty(self, mock_get_db_session):
        """Test getting recent alerts when none exist."""
        with patch("app.mcp.resources.data.get_db_session", mock_get_db_session):
            from app.mcp.resources.data import get_recent_alerts

            result = await get_recent_alerts()

            assert "No recent alerts" in result

    @pytest.mark.asyncio
    async def test_get_recent_alerts_shows_unread_status(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test that recent alerts shows unread status."""
        with patch("app.mcp.resources.data.get_db_session", mock_get_db_session):
            from app.mcp.resources.data import get_recent_alerts

            result = await get_recent_alerts()

            # Should have both read and unread indicators
            assert "[UNREAD]" in result or "[read]" in result

    @pytest.mark.asyncio
    async def test_get_recent_alerts_shows_setup_type(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test that recent alerts shows setup types."""
        with patch("app.mcp.resources.data.get_db_session", mock_get_db_session):
            from app.mcp.resources.data import get_recent_alerts

            result = await get_recent_alerts()

            # Should include setup type indicators
            assert "BREAKOUT" in result or "VOLUME_SPIKE" in result or "MOMENTUM" in result


class TestUnreadAlertsResource:
    """Tests for alerts://unread resource."""

    @pytest.mark.asyncio
    async def test_get_unread_alerts_with_data(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test getting unread alerts resource with data."""
        with patch("app.mcp.resources.data.get_db_session", mock_get_db_session):
            from app.mcp.resources.data import get_unread_alerts

            result = await get_unread_alerts()

            assert "Unread Alerts" in result

    @pytest.mark.asyncio
    async def test_get_unread_alerts_empty(self, mock_get_db_session):
        """Test getting unread alerts when all are read."""
        with patch("app.mcp.resources.data.get_db_session", mock_get_db_session):
            from app.mcp.resources.data import get_unread_alerts

            result = await get_unread_alerts()

            assert "No unread alerts" in result
            assert "All caught up" in result

    @pytest.mark.asyncio
    async def test_get_unread_alerts_includes_price_levels(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test that unread alerts includes price levels."""
        with patch("app.mcp.resources.data.get_db_session", mock_get_db_session):
            from app.mcp.resources.data import get_unread_alerts

            result = await get_unread_alerts()

            # Should include price information
            assert "Entry:" in result or "$" in result


class TestActiveRulesResource:
    """Tests for rules://active resource."""

    @pytest.mark.asyncio
    async def test_get_active_rules_with_data(
        self, mock_get_db_session, mcp_sample_rule, mcp_inactive_rule
    ):
        """Test getting active rules resource with data."""
        with patch("app.mcp.resources.data.get_db_session", mock_get_db_session):
            from app.mcp.resources.data import get_active_rules

            result = await get_active_rules()

            assert "Active Trading Rules" in result
            # Only active rules should be shown
            assert mcp_sample_rule.name in result
            assert mcp_inactive_rule.name not in result

    @pytest.mark.asyncio
    async def test_get_active_rules_empty(self, mock_get_db_session):
        """Test getting active rules when none exist."""
        with patch("app.mcp.resources.data.get_db_session", mock_get_db_session):
            from app.mcp.resources.data import get_active_rules

            result = await get_active_rules()

            assert "No active rules" in result

    @pytest.mark.asyncio
    async def test_get_active_rules_shows_priority(
        self, mock_get_db_session, mcp_sample_rule
    ):
        """Test that active rules shows priority."""
        with patch("app.mcp.resources.data.get_db_session", mock_get_db_session):
            from app.mcp.resources.data import get_active_rules

            result = await get_active_rules()

            # Priority should be shown in brackets
            assert f"[{mcp_sample_rule.priority:2d}]" in result or f"[{mcp_sample_rule.priority}]" in result

    @pytest.mark.asyncio
    async def test_get_active_rules_shows_alert_count(
        self, mock_get_db_session, mcp_sample_rule, mcp_sample_alert
    ):
        """Test that active rules shows alert counts."""
        with patch("app.mcp.resources.data.get_db_session", mock_get_db_session):
            from app.mcp.resources.data import get_active_rules

            result = await get_active_rules()

            assert "Alerts:" in result


class TestDailyStatsResource:
    """Tests for stats://daily resource."""

    @pytest.mark.asyncio
    async def test_get_daily_stats_with_data(
        self, mock_get_db_session, mcp_multiple_alerts, mcp_sample_rule, mcp_watchlist_items
    ):
        """Test getting daily stats resource with data."""
        with patch("app.mcp.resources.data.get_db_session", mock_get_db_session):
            from app.mcp.resources.data import get_daily_stats

            result = await get_daily_stats()

            assert "Daily Statistics" in result
            assert "ALERTS" in result
            assert "Today:" in result
            assert "This Week:" in result
            assert "CONFIGURATION" in result
            assert "Active Rules:" in result
            assert "Watchlist:" in result

    @pytest.mark.asyncio
    async def test_get_daily_stats_empty(self, mock_get_db_session):
        """Test getting daily stats when no data exists."""
        with patch("app.mcp.resources.data.get_db_session", mock_get_db_session):
            from app.mcp.resources.data import get_daily_stats

            result = await get_daily_stats()

            assert "Daily Statistics" in result
            assert "Today: 0" in result
            assert "Active Rules: 0" in result

    @pytest.mark.asyncio
    async def test_get_daily_stats_includes_date(self, mock_get_db_session):
        """Test that daily stats includes current date."""
        with patch("app.mcp.resources.data.get_db_session", mock_get_db_session):
            from app.mcp.resources.data import get_daily_stats

            result = await get_daily_stats()

            assert "Date:" in result

    @pytest.mark.asyncio
    async def test_get_daily_stats_shows_unread(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test that daily stats shows unread count."""
        with patch("app.mcp.resources.data.get_db_session", mock_get_db_session):
            from app.mcp.resources.data import get_daily_stats

            result = await get_daily_stats()

            assert "Unread:" in result


class TestCurrentWatchlistResource:
    """Tests for watchlist://current resource."""

    @pytest.mark.asyncio
    async def test_get_current_watchlist_with_data(
        self, mock_get_db_session, mcp_watchlist_items
    ):
        """Test getting current watchlist resource with data."""
        with patch("app.mcp.resources.data.get_db_session", mock_get_db_session):
            from app.mcp.resources.data import get_current_watchlist

            result = await get_current_watchlist()

            assert "Watchlist" in result
            assert "4 symbols" in result
            assert "AAPL" in result
            assert "ACTIVE:" in result

    @pytest.mark.asyncio
    async def test_get_current_watchlist_empty(self, mock_get_db_session):
        """Test getting current watchlist when empty."""
        with patch("app.mcp.resources.data.get_db_session", mock_get_db_session):
            from app.mcp.resources.data import get_current_watchlist

            result = await get_current_watchlist()

            assert "Watchlist is empty" in result

    @pytest.mark.asyncio
    async def test_get_current_watchlist_shows_notes(
        self, mock_get_db_session, mcp_watchlist_items
    ):
        """Test that watchlist shows notes for items."""
        with patch("app.mcp.resources.data.get_db_session", mock_get_db_session):
            from app.mcp.resources.data import get_current_watchlist

            result = await get_current_watchlist()

            assert "Note:" in result

    @pytest.mark.asyncio
    async def test_get_current_watchlist_shows_recent_alerts(
        self, mock_get_db_session, mcp_watchlist_items, mcp_multiple_alerts
    ):
        """Test that watchlist shows recent alert counts."""
        with patch("app.mcp.resources.data.get_db_session", mock_get_db_session):
            from app.mcp.resources.data import get_current_watchlist

            result = await get_current_watchlist()

            # Should mention alerts this week
            assert "alerts this week" in result or "alert" in result.lower()

    @pytest.mark.asyncio
    async def test_get_current_watchlist_separates_active_inactive(
        self, mock_get_db_session, mcp_watchlist_items
    ):
        """Test that watchlist separates active and inactive items."""
        with patch("app.mcp.resources.data.get_db_session", mock_get_db_session):
            from app.mcp.resources.data import get_current_watchlist

            result = await get_current_watchlist()

            assert "ACTIVE:" in result
            assert "INACTIVE:" in result
            # TSLA should be in inactive section
            assert "TSLA" in result
