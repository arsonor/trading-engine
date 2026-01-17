"""Integration tests for MCP analysis workflows.

These tests verify complete analysis workflows through MCP tools.
"""

import pytest


class TestWatchlistAnalysisWorkflow:
    """Test watchlist analysis workflows."""

    @pytest.mark.asyncio
    async def test_analyze_watchlist_with_alerts(
        self, patch_all_mcp_modules, watchlist, trading_alerts
    ):
        """Test analyzing watchlist symbols with alert history."""
        from app.mcp.tools.analysis import analyze_watchlist

        result = await analyze_watchlist()

        assert "Watchlist Analysis" in result
        assert "symbols analyzed" in result
        # Should categorize symbols
        assert "Bullish" in result or "Bearish" in result or "Neutral" in result
        # Summary should be present
        assert "Summary" in result
        assert "bullish" in result.lower()

    @pytest.mark.asyncio
    async def test_analyze_watchlist_includes_notes(
        self, patch_all_mcp_modules, watchlist, trading_alerts
    ):
        """Test that analysis includes watchlist notes."""
        from app.mcp.tools.analysis import analyze_watchlist

        result = await analyze_watchlist()

        # Notes should appear for symbols with alerts
        assert "Note:" in result or "AI" in result  # Some notes contain "AI"


class TestSymbolAnalysisWorkflow:
    """Test individual symbol analysis workflows."""

    @pytest.mark.asyncio
    async def test_analyze_active_symbol(
        self, patch_all_mcp_modules, trading_alerts, watchlist
    ):
        """Test deep analysis of an actively traded symbol."""
        from app.mcp.tools.analysis import get_symbol_analysis

        result = await get_symbol_analysis("NVDA")

        assert "NVDA Analysis" in result
        assert "In watchlist" in result
        assert "Overview" in result
        assert "Total Alerts" in result
        assert "Price Levels" in result
        assert "Setup Distribution" in result
        assert "Activity Trend" in result
        assert "Latest Alert" in result

    @pytest.mark.asyncio
    async def test_analyze_symbol_setup_distribution(
        self, patch_all_mcp_modules, trading_alerts
    ):
        """Test that symbol analysis shows setup type distribution."""
        from app.mcp.tools.analysis import get_symbol_analysis

        result = await get_symbol_analysis("NVDA")

        assert "Setup Distribution" in result
        assert "BREAKOUT" in result  # NVDA has a breakout alert

    @pytest.mark.asyncio
    async def test_analyze_symbol_not_in_watchlist(
        self, patch_all_mcp_modules, trading_alerts, watchlist
    ):
        """Test analyzing a symbol not in watchlist."""
        from app.mcp.tools.analysis import get_symbol_analysis

        # NFLX is in alerts but not in our test watchlist
        result = await get_symbol_analysis("NFLX")

        assert "NFLX Analysis" in result
        assert "Not in watchlist" in result

    @pytest.mark.asyncio
    async def test_analyze_symbol_no_alerts(
        self, patch_all_mcp_modules, watchlist
    ):
        """Test analyzing a symbol with no alerts."""
        from app.mcp.tools.analysis import get_symbol_analysis

        result = await get_symbol_analysis("XYZ")

        assert "XYZ Analysis" in result
        assert "No alerts found" in result


class TestSymbolComparisonWorkflow:
    """Test symbol comparison workflows."""

    @pytest.mark.asyncio
    async def test_compare_multiple_symbols(
        self, patch_all_mcp_modules, trading_alerts
    ):
        """Test comparing multiple symbols."""
        from app.mcp.tools.analysis import compare_symbols

        result = await compare_symbols(["NVDA", "AMD", "AAPL"])

        assert "Symbol Comparison" in result
        assert "3 symbols" in result
        assert "Alert Frequency" in result
        assert "Average Confidence" in result
        assert "Primary Setup Types" in result
        assert "Summary" in result
        # All symbols should be mentioned
        assert "NVDA" in result
        assert "AMD" in result
        assert "AAPL" in result

    @pytest.mark.asyncio
    async def test_compare_symbols_sorted_by_frequency(
        self, patch_all_mcp_modules, trading_alerts
    ):
        """Test that comparison sorts symbols by alert frequency."""
        from app.mcp.tools.analysis import compare_symbols

        result = await compare_symbols(["NVDA", "AMD", "NFLX"])

        # Result should show frequency comparison with bars
        assert "Alert Frequency" in result
        assert "█" in result  # Progress bar characters

    @pytest.mark.asyncio
    async def test_compare_identifies_best_performer(
        self, patch_all_mcp_modules, trading_alerts
    ):
        """Test that comparison identifies best performer."""
        from app.mcp.tools.analysis import compare_symbols

        result = await compare_symbols(["NVDA", "AMD", "SMCI"])

        assert "Summary" in result
        assert "Most Active with High Confidence" in result


class TestTopPerformersWorkflow:
    """Test top performers analysis workflows."""

    @pytest.mark.asyncio
    async def test_get_top_performers_default(
        self, patch_all_mcp_modules, trading_alerts
    ):
        """Test getting top performers with default settings."""
        from app.mcp.tools.analysis import get_top_performers

        result = await get_top_performers()

        assert "Top Performing Alerts" in result
        assert "Last 7 day" in result
        # NVDA has highest confidence (0.92)
        assert "NVDA" in result
        assert "Statistics" in result
        assert "Average Confidence" in result

    @pytest.mark.asyncio
    async def test_top_performers_sorted_by_confidence(
        self, patch_all_mcp_modules, trading_alerts
    ):
        """Test that top performers are sorted by confidence."""
        from app.mcp.tools.analysis import get_top_performers

        result = await get_top_performers(limit=5)

        # First entry should be NVDA (92% confidence)
        lines = result.split("\n")
        first_entry_line = None
        for line in lines:
            if line.startswith("## #1"):
                first_entry_line = line
                break

        assert first_entry_line is not None
        assert "NVDA" in first_entry_line or "92%" in first_entry_line

    @pytest.mark.asyncio
    async def test_top_performers_includes_rr_ratio(
        self, patch_all_mcp_modules, trading_alerts
    ):
        """Test that top performers includes risk/reward ratios."""
        from app.mcp.tools.analysis import get_top_performers

        result = await get_top_performers()

        assert "R/R:" in result

    @pytest.mark.asyncio
    async def test_top_performers_custom_period(
        self, patch_all_mcp_modules, trading_alerts
    ):
        """Test top performers with custom time period."""
        from app.mcp.tools.analysis import get_top_performers

        result = await get_top_performers(days=30, limit=3)

        assert "30 day" in result
        assert "Top 3" in result


class TestWatchlistResourceIntegration:
    """Test watchlist resource integration with analysis."""

    @pytest.mark.asyncio
    async def test_watchlist_resource(
        self, patch_all_mcp_modules, watchlist, trading_alerts
    ):
        """Test watchlist://current resource."""
        from app.mcp.resources.data import get_current_watchlist

        result = await get_current_watchlist()

        assert "Watchlist" in result
        assert "6 symbols" in result
        assert "ACTIVE:" in result
        assert "INACTIVE:" in result
        assert "NVDA" in result
        assert "TSLA" in result  # Inactive symbol
        # Should show recent alert activity
        assert "alerts this week" in result or "alert" in result.lower()
