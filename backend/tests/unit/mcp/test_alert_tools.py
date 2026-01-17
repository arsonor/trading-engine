"""Unit tests for MCP alert tools."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
import pytest_asyncio

from app.models.alert import Alert
from app.models.rule import Rule


class TestExplainAlert:
    """Tests for explain_alert tool."""

    @pytest.mark.asyncio
    async def test_explain_existing_alert(
        self, mock_get_db_session, mcp_sample_alert, mcp_sample_rule
    ):
        """Test explaining an existing alert returns detailed information."""
        with patch("app.mcp.tools.alerts.get_db_session", mock_get_db_session):
            from app.mcp.tools.alerts import explain_alert

            result = await explain_alert(mcp_sample_alert.id)

            assert f"Alert #{mcp_sample_alert.id}" in result
            assert "AAPL" in result
            assert "BREAKOUT" in result
            assert "$150.50" in result
            assert "Stop Loss" in result
            assert "Target Price" in result
            assert "Risk/Reward Ratio" in result
            assert mcp_sample_rule.name in result

    @pytest.mark.asyncio
    async def test_explain_nonexistent_alert(self, mock_get_db_session):
        """Test explaining a non-existent alert returns appropriate message."""
        with patch("app.mcp.tools.alerts.get_db_session", mock_get_db_session):
            from app.mcp.tools.alerts import explain_alert

            result = await explain_alert(99999)

            assert "not found" in result.lower()
            assert "99999" in result

    @pytest.mark.asyncio
    async def test_explain_alert_with_market_data(
        self, mock_get_db_session, mcp_sample_alert
    ):
        """Test that market data is included in explanation."""
        with patch("app.mcp.tools.alerts.get_db_session", mock_get_db_session):
            from app.mcp.tools.alerts import explain_alert

            result = await explain_alert(mcp_sample_alert.id)

            assert "Market Conditions" in result
            assert "Volume" in result
            assert "Volume Ratio" in result


class TestListAlerts:
    """Tests for list_alerts tool."""

    @pytest.mark.asyncio
    async def test_list_alerts_default(self, mock_get_db_session, mcp_multiple_alerts):
        """Test listing alerts with default parameters."""
        with patch("app.mcp.tools.alerts.get_db_session", mock_get_db_session):
            from app.mcp.tools.alerts import list_alerts

            result = await list_alerts()

            assert "Recent Alerts" in result
            # Should include some of the test alerts
            assert "AAPL" in result or "GOOGL" in result

    @pytest.mark.asyncio
    async def test_list_alerts_by_symbol(self, mock_get_db_session, mcp_multiple_alerts):
        """Test filtering alerts by symbol."""
        with patch("app.mcp.tools.alerts.get_db_session", mock_get_db_session):
            from app.mcp.tools.alerts import list_alerts

            result = await list_alerts(symbol="AAPL")

            assert "AAPL" in result
            # Should not include other symbols in the main output
            assert "GOOGL" not in result or "symbol=AAPL" in result

    @pytest.mark.asyncio
    async def test_list_alerts_by_setup_type(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test filtering alerts by setup type."""
        with patch("app.mcp.tools.alerts.get_db_session", mock_get_db_session):
            from app.mcp.tools.alerts import list_alerts

            result = await list_alerts(setup_type="breakout")

            assert "BREAKOUT" in result

    @pytest.mark.asyncio
    async def test_list_alerts_unread_only(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test filtering for unread alerts only."""
        with patch("app.mcp.tools.alerts.get_db_session", mock_get_db_session):
            from app.mcp.tools.alerts import list_alerts

            result = await list_alerts(unread_only=True)

            # Unread alerts use blue circle emoji
            assert "unread" in result.lower() or "🔵" in result

    @pytest.mark.asyncio
    async def test_list_alerts_with_limit(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test limiting number of alerts returned."""
        with patch("app.mcp.tools.alerts.get_db_session", mock_get_db_session):
            from app.mcp.tools.alerts import list_alerts

            result = await list_alerts(limit=3)

            assert "3 shown" in result

    @pytest.mark.asyncio
    async def test_list_alerts_empty(self, mock_get_db_session):
        """Test listing alerts when none exist."""
        with patch("app.mcp.tools.alerts.get_db_session", mock_get_db_session):
            from app.mcp.tools.alerts import list_alerts

            result = await list_alerts()

            assert "No alerts found" in result


class TestGetAlertStatistics:
    """Tests for get_alert_statistics tool."""

    @pytest.mark.asyncio
    async def test_get_statistics_default(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test getting statistics with default parameters."""
        with patch("app.mcp.tools.alerts.get_db_session", mock_get_db_session):
            from app.mcp.tools.alerts import get_alert_statistics

            result = await get_alert_statistics()

            assert "Alert Statistics" in result
            assert "7 Day" in result
            assert "Overview" in result
            assert "Total Alerts" in result
            assert "Daily Average" in result

    @pytest.mark.asyncio
    async def test_get_statistics_custom_days(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test getting statistics for custom time period."""
        with patch("app.mcp.tools.alerts.get_db_session", mock_get_db_session):
            from app.mcp.tools.alerts import get_alert_statistics

            result = await get_alert_statistics(days=30)

            assert "30 Days" in result

    @pytest.mark.asyncio
    async def test_get_statistics_by_setup_type(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test that statistics include setup type breakdown."""
        with patch("app.mcp.tools.alerts.get_db_session", mock_get_db_session):
            from app.mcp.tools.alerts import get_alert_statistics

            result = await get_alert_statistics()

            assert "By Setup Type" in result
            assert "BREAKOUT" in result or "VOLUME_SPIKE" in result

    @pytest.mark.asyncio
    async def test_get_statistics_by_symbol(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test that statistics include top symbols."""
        with patch("app.mcp.tools.alerts.get_db_session", mock_get_db_session):
            from app.mcp.tools.alerts import get_alert_statistics

            result = await get_alert_statistics()

            assert "Top Symbols" in result

    @pytest.mark.asyncio
    async def test_get_statistics_confidence_metrics(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test that confidence metrics are included."""
        with patch("app.mcp.tools.alerts.get_db_session", mock_get_db_session):
            from app.mcp.tools.alerts import get_alert_statistics

            result = await get_alert_statistics()

            assert "Confidence" in result

    @pytest.mark.asyncio
    async def test_get_statistics_clamps_days(self, mock_get_db_session):
        """Test that days parameter is clamped to valid range."""
        with patch("app.mcp.tools.alerts.get_db_session", mock_get_db_session):
            from app.mcp.tools.alerts import get_alert_statistics

            # Test with very large value (should be clamped to 90)
            result = await get_alert_statistics(days=999)
            assert "90 Days" in result

            # Test with negative value (should be clamped to 1)
            result = await get_alert_statistics(days=-5)
            assert "1 Day" in result


class TestGetAlertById:
    """Tests for get_alert_by_id tool."""

    @pytest.mark.asyncio
    async def test_get_existing_alert(
        self, mock_get_db_session, mcp_sample_alert, mcp_sample_rule
    ):
        """Test getting an existing alert by ID."""
        with patch("app.mcp.tools.alerts.get_db_session", mock_get_db_session):
            from app.mcp.tools.alerts import get_alert_by_id

            result = await get_alert_by_id(mcp_sample_alert.id)

            assert f"Alert #{mcp_sample_alert.id}" in result
            assert "AAPL" in result
            assert "BREAKOUT" in result
            assert "$150.50" in result
            assert "Price Levels" in result

    @pytest.mark.asyncio
    async def test_get_nonexistent_alert(self, mock_get_db_session):
        """Test getting a non-existent alert returns appropriate message."""
        with patch("app.mcp.tools.alerts.get_db_session", mock_get_db_session):
            from app.mcp.tools.alerts import get_alert_by_id

            result = await get_alert_by_id(99999)

            assert "not found" in result.lower()
            assert "99999" in result

    @pytest.mark.asyncio
    async def test_get_alert_includes_rule_info(
        self, mock_get_db_session, mcp_sample_alert, mcp_sample_rule
    ):
        """Test that alert includes associated rule information."""
        with patch("app.mcp.tools.alerts.get_db_session", mock_get_db_session):
            from app.mcp.tools.alerts import get_alert_by_id

            result = await get_alert_by_id(mcp_sample_alert.id)

            assert "Rule" in result
            assert mcp_sample_rule.name in result

    @pytest.mark.asyncio
    async def test_get_alert_includes_market_data(
        self, mock_get_db_session, mcp_sample_alert
    ):
        """Test that alert includes market data when available."""
        with patch("app.mcp.tools.alerts.get_db_session", mock_get_db_session):
            from app.mcp.tools.alerts import get_alert_by_id

            result = await get_alert_by_id(mcp_sample_alert.id)

            assert "Market Data" in result
            assert "Volume" in result


class TestMarkAlertRead:
    """Tests for mark_alert_read tool."""

    @pytest.mark.asyncio
    async def test_mark_unread_alert_as_read(
        self, mock_get_db_session, mcp_sample_alert
    ):
        """Test marking an unread alert as read."""
        assert mcp_sample_alert.is_read is False

        with patch("app.mcp.tools.alerts.get_db_session", mock_get_db_session):
            from app.mcp.tools.alerts import mark_alert_read

            result = await mark_alert_read(mcp_sample_alert.id)

            assert "marked as read" in result.lower()
            assert str(mcp_sample_alert.id) in result
            assert "AAPL" in result

    @pytest.mark.asyncio
    async def test_mark_already_read_alert(
        self, mock_get_db_session, mcp_db_session, mcp_sample_rule
    ):
        """Test marking an already read alert."""
        # Create a read alert
        alert = Alert(
            rule_id=mcp_sample_rule.id,
            symbol="TEST",
            timestamp=datetime.utcnow(),
            setup_type="breakout",
            entry_price=100.0,
            is_read=True,
        )
        mcp_db_session.add(alert)
        await mcp_db_session.commit()
        await mcp_db_session.refresh(alert)

        with patch("app.mcp.tools.alerts.get_db_session", mock_get_db_session):
            from app.mcp.tools.alerts import mark_alert_read

            result = await mark_alert_read(alert.id)

            assert "already" in result.lower()

    @pytest.mark.asyncio
    async def test_mark_nonexistent_alert(self, mock_get_db_session):
        """Test marking a non-existent alert returns appropriate message."""
        with patch("app.mcp.tools.alerts.get_db_session", mock_get_db_session):
            from app.mcp.tools.alerts import mark_alert_read

            result = await mark_alert_read(99999)

            assert "not found" in result.lower()
            assert "99999" in result
