"""Unit tests for MCP analysis tools."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.models.alert import Alert


class TestAnalyzeWatchlist:
    """Tests for analyze_watchlist tool."""

    @pytest.mark.asyncio
    async def test_analyze_watchlist_with_data(
        self, mock_get_db_session, mcp_watchlist_items, mcp_multiple_alerts
    ):
        """Test analyzing watchlist with alerts data."""
        with patch("app.mcp.tools.analysis.get_db_session", mock_get_db_session):
            from app.mcp.tools.analysis import analyze_watchlist

            result = await analyze_watchlist()

            assert "Watchlist Analysis" in result
            assert "symbols analyzed" in result
            # Should include signal sections
            assert "Bullish" in result or "Bearish" in result or "Neutral" in result

    @pytest.mark.asyncio
    async def test_analyze_empty_watchlist(self, mock_get_db_session):
        """Test analyzing an empty watchlist."""
        with patch("app.mcp.tools.analysis.get_db_session", mock_get_db_session):
            from app.mcp.tools.analysis import analyze_watchlist

            result = await analyze_watchlist()

            assert "No symbols in watchlist" in result

    @pytest.mark.asyncio
    async def test_analyze_watchlist_summary(
        self, mock_get_db_session, mcp_watchlist_items, mcp_multiple_alerts
    ):
        """Test that watchlist analysis includes summary."""
        with patch("app.mcp.tools.analysis.get_db_session", mock_get_db_session):
            from app.mcp.tools.analysis import analyze_watchlist

            result = await analyze_watchlist()

            assert "Summary" in result
            assert "bullish" in result.lower()
            assert "bearish" in result.lower()
            assert "neutral" in result.lower()


class TestGetSymbolAnalysis:
    """Tests for get_symbol_analysis tool."""

    @pytest.mark.asyncio
    async def test_analyze_symbol_with_alerts(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test analyzing a symbol that has alerts."""
        with patch("app.mcp.tools.analysis.get_db_session", mock_get_db_session):
            from app.mcp.tools.analysis import get_symbol_analysis

            result = await get_symbol_analysis("AAPL")

            assert "AAPL Analysis" in result
            assert "Overview" in result
            assert "Total Alerts" in result
            assert "Price Levels" in result
            assert "Setup Distribution" in result

    @pytest.mark.asyncio
    async def test_analyze_symbol_case_insensitive(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test that symbol analysis is case insensitive."""
        with patch("app.mcp.tools.analysis.get_db_session", mock_get_db_session):
            from app.mcp.tools.analysis import get_symbol_analysis

            result = await get_symbol_analysis("aapl")  # lowercase

            assert "AAPL Analysis" in result

    @pytest.mark.asyncio
    async def test_analyze_symbol_no_alerts(self, mock_get_db_session):
        """Test analyzing a symbol with no alerts."""
        with patch("app.mcp.tools.analysis.get_db_session", mock_get_db_session):
            from app.mcp.tools.analysis import get_symbol_analysis

            result = await get_symbol_analysis("XYZ")

            assert "XYZ Analysis" in result
            assert "No alerts found" in result

    @pytest.mark.asyncio
    async def test_analyze_symbol_shows_watchlist_status(
        self, mock_get_db_session, mcp_watchlist_items, mcp_multiple_alerts
    ):
        """Test that analysis shows if symbol is in watchlist."""
        with patch("app.mcp.tools.analysis.get_db_session", mock_get_db_session):
            from app.mcp.tools.analysis import get_symbol_analysis

            # AAPL is in the watchlist
            result = await get_symbol_analysis("AAPL")
            assert "In watchlist" in result

            # NVDA is not in the test watchlist
            result = await get_symbol_analysis("NVDA")
            assert "Not in watchlist" in result

    @pytest.mark.asyncio
    async def test_analyze_symbol_includes_latest_alert(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test that analysis includes latest alert information."""
        with patch("app.mcp.tools.analysis.get_db_session", mock_get_db_session):
            from app.mcp.tools.analysis import get_symbol_analysis

            result = await get_symbol_analysis("AAPL")

            assert "Latest Alert" in result
            assert "Type:" in result
            assert "Entry:" in result

    @pytest.mark.asyncio
    async def test_analyze_symbol_includes_activity_trend(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test that analysis includes activity trend."""
        with patch("app.mcp.tools.analysis.get_db_session", mock_get_db_session):
            from app.mcp.tools.analysis import get_symbol_analysis

            result = await get_symbol_analysis("AAPL")

            assert "Activity Trend" in result


class TestCompareSymbols:
    """Tests for compare_symbols tool."""

    @pytest.mark.asyncio
    async def test_compare_multiple_symbols(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test comparing multiple symbols."""
        with patch("app.mcp.tools.analysis.get_db_session", mock_get_db_session):
            from app.mcp.tools.analysis import compare_symbols

            result = await compare_symbols(["AAPL", "GOOGL", "MSFT"])

            assert "Symbol Comparison" in result
            assert "3 symbols" in result
            assert "Alert Frequency" in result
            assert "AAPL" in result
            assert "GOOGL" in result
            assert "MSFT" in result

    @pytest.mark.asyncio
    async def test_compare_symbols_case_insensitive(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test that comparison is case insensitive."""
        with patch("app.mcp.tools.analysis.get_db_session", mock_get_db_session):
            from app.mcp.tools.analysis import compare_symbols

            result = await compare_symbols(["aapl", "googl"])

            assert "AAPL" in result
            assert "GOOGL" in result

    @pytest.mark.asyncio
    async def test_compare_empty_list(self, mock_get_db_session):
        """Test comparing with empty list."""
        with patch("app.mcp.tools.analysis.get_db_session", mock_get_db_session):
            from app.mcp.tools.analysis import compare_symbols

            result = await compare_symbols([])

            assert "Please provide" in result

    @pytest.mark.asyncio
    async def test_compare_too_many_symbols(self, mock_get_db_session):
        """Test comparing more than 10 symbols."""
        with patch("app.mcp.tools.analysis.get_db_session", mock_get_db_session):
            from app.mcp.tools.analysis import compare_symbols

            symbols = [f"SYM{i}" for i in range(15)]
            result = await compare_symbols(symbols)

            assert "limit" in result.lower() or "10 symbols" in result

    @pytest.mark.asyncio
    async def test_compare_includes_confidence(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test that comparison includes confidence metrics."""
        with patch("app.mcp.tools.analysis.get_db_session", mock_get_db_session):
            from app.mcp.tools.analysis import compare_symbols

            result = await compare_symbols(["AAPL", "NVDA"])

            assert "Confidence" in result

    @pytest.mark.asyncio
    async def test_compare_includes_setup_types(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test that comparison includes setup type information."""
        with patch("app.mcp.tools.analysis.get_db_session", mock_get_db_session):
            from app.mcp.tools.analysis import compare_symbols

            result = await compare_symbols(["AAPL", "GOOGL"])

            assert "Setup Types" in result

    @pytest.mark.asyncio
    async def test_compare_includes_summary(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test that comparison includes summary."""
        with patch("app.mcp.tools.analysis.get_db_session", mock_get_db_session):
            from app.mcp.tools.analysis import compare_symbols

            result = await compare_symbols(["AAPL", "NVDA"])

            assert "Summary" in result


class TestGetTopPerformers:
    """Tests for get_top_performers tool."""

    @pytest.mark.asyncio
    async def test_get_top_performers_default(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test getting top performers with default parameters."""
        with patch("app.mcp.tools.analysis.get_db_session", mock_get_db_session):
            from app.mcp.tools.analysis import get_top_performers

            result = await get_top_performers()

            assert "Top Performing Alerts" in result
            assert "Last 7 day" in result

    @pytest.mark.asyncio
    async def test_get_top_performers_custom_days(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test getting top performers for custom time period."""
        with patch("app.mcp.tools.analysis.get_db_session", mock_get_db_session):
            from app.mcp.tools.analysis import get_top_performers

            result = await get_top_performers(days=30)

            assert "30 day" in result

    @pytest.mark.asyncio
    async def test_get_top_performers_custom_limit(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test getting top performers with custom limit."""
        with patch("app.mcp.tools.analysis.get_db_session", mock_get_db_session):
            from app.mcp.tools.analysis import get_top_performers

            result = await get_top_performers(limit=3)

            assert "Top 3" in result

    @pytest.mark.asyncio
    async def test_get_top_performers_no_data(self, mock_get_db_session):
        """Test getting top performers when no alerts exist."""
        with patch("app.mcp.tools.analysis.get_db_session", mock_get_db_session):
            from app.mcp.tools.analysis import get_top_performers

            result = await get_top_performers()

            assert "No alerts" in result

    @pytest.mark.asyncio
    async def test_get_top_performers_sorted_by_confidence(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test that top performers are sorted by confidence."""
        with patch("app.mcp.tools.analysis.get_db_session", mock_get_db_session):
            from app.mcp.tools.analysis import get_top_performers

            result = await get_top_performers()

            # The first entry should have highest confidence
            # NVDA has 95% confidence in our test data
            lines = result.split("\n")
            first_entry_found = False
            for line in lines:
                if line.startswith("## #1"):
                    first_entry_found = True
                    assert "95%" in line or "NVDA" in line
                    break

    @pytest.mark.asyncio
    async def test_get_top_performers_includes_rr_ratio(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test that top performers include risk/reward ratio."""
        with patch("app.mcp.tools.analysis.get_db_session", mock_get_db_session):
            from app.mcp.tools.analysis import get_top_performers

            result = await get_top_performers()

            # Alerts have stop_loss and target_price, so R/R should be calculated
            assert "R/R" in result

    @pytest.mark.asyncio
    async def test_get_top_performers_clamps_parameters(self, mock_get_db_session):
        """Test that parameters are clamped to valid ranges."""
        with patch("app.mcp.tools.analysis.get_db_session", mock_get_db_session):
            from app.mcp.tools.analysis import get_top_performers

            # Very large days should be clamped to 90
            result = await get_top_performers(days=999)
            assert "90 day" in result or "No alerts" in result

            # Negative should be clamped to 1
            result = await get_top_performers(days=-5)
            assert "1 day" in result or "No alerts" in result

    @pytest.mark.asyncio
    async def test_get_top_performers_includes_statistics(
        self, mock_get_db_session, mcp_multiple_alerts
    ):
        """Test that top performers include summary statistics."""
        with patch("app.mcp.tools.analysis.get_db_session", mock_get_db_session):
            from app.mcp.tools.analysis import get_top_performers

            result = await get_top_performers()

            assert "Statistics" in result
            assert "Average Confidence" in result
            assert "Most Common Setup" in result
            assert "Unique Symbols" in result


class TestAnalyzeSymbolAlerts:
    """Tests for _analyze_symbol_alerts helper function."""

    def test_analyze_empty_alerts(self):
        """Test analyzing empty alerts list."""
        from app.mcp.tools.analysis import _analyze_symbol_alerts

        result = _analyze_symbol_alerts([])

        assert result["signal"] == "neutral"
        assert "No recent alerts" in result["summary"]

    def test_analyze_bullish_alerts(self, mcp_db_session, mcp_sample_rule):
        """Test analyzing bullish alert patterns."""
        from app.mcp.tools.analysis import _analyze_symbol_alerts

        # Create mock alerts with bullish setup types
        class MockAlert:
            def __init__(self, setup_type, confidence):
                self.setup_type = setup_type
                self.confidence_score = confidence

        alerts = [
            MockAlert("breakout", 0.85),
            MockAlert("gap_up", 0.80),
            MockAlert("momentum", 0.75),
        ]

        result = _analyze_symbol_alerts(alerts)

        assert result["signal"] == "bullish"
        assert "3 alert" in result["summary"]

    def test_analyze_bearish_alerts(self):
        """Test analyzing bearish alert patterns."""
        from app.mcp.tools.analysis import _analyze_symbol_alerts

        class MockAlert:
            def __init__(self, setup_type, confidence):
                self.setup_type = setup_type
                self.confidence_score = confidence

        alerts = [
            MockAlert("gap_down", 0.85),
            MockAlert("gap_down", 0.80),
        ]

        result = _analyze_symbol_alerts(alerts)

        assert result["signal"] == "bearish"
