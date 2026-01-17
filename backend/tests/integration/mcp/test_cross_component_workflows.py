"""Integration tests for MCP cross-component workflows.

These tests verify workflows that span multiple MCP components,
simulating realistic user interactions with the trading engine.
"""

import pytest


class TestCompleteTradeResearchWorkflow:
    """Test complete trade research workflow across components."""

    @pytest.mark.asyncio
    async def test_research_new_symbol_workflow(
        self, patch_all_mcp_modules, trading_alerts, watchlist
    ):
        """Test researching a new symbol and adding to watchlist."""
        from app.mcp.tools.analysis import get_symbol_analysis
        from app.mcp.tools.watchlist import add_to_watchlist, get_watchlist

        # Step 1: Analyze a symbol not in watchlist
        analysis = await get_symbol_analysis("AMZN")
        assert "AMZN Analysis" in analysis
        assert "Not in watchlist" in analysis

        # Step 2: Add to watchlist based on analysis
        add_result = await add_to_watchlist("AMZN", notes="Adding after positive analysis")
        assert "Added to Watchlist" in add_result
        assert "AMZN" in add_result

        # Step 3: Verify in watchlist
        watchlist_result = await get_watchlist()
        assert "AMZN" in watchlist_result
        assert "Adding after positive analysis" in watchlist_result

    @pytest.mark.asyncio
    async def test_alert_investigation_workflow(
        self, patch_all_mcp_modules, trading_alerts, trading_rules
    ):
        """Test investigating an alert and understanding the triggering rule."""
        from app.mcp.tools.alerts import explain_alert, list_alerts
        from app.mcp.tools.rules import get_rule

        # Step 1: List recent high-confidence alerts
        alerts_list = await list_alerts(limit=3)
        assert "Recent Alerts" in alerts_list

        # Step 2: Get details on the top alert (NVDA)
        nvda_alert = next(a for a in trading_alerts if a.symbol == "NVDA")
        explanation = await explain_alert(nvda_alert.id)
        assert "NVDA" in explanation
        assert "High Volume Breakout" in explanation  # Rule name

        # Step 3: Investigate the rule that triggered it
        rule = next(r for r in trading_rules if r.name == "High Volume Breakout")
        rule_details = await get_rule(rule.id)
        assert "High Volume Breakout" in rule_details
        assert "Configuration" in rule_details
        assert "price_change_percent" in rule_details

    @pytest.mark.asyncio
    async def test_portfolio_monitoring_workflow(
        self, patch_all_mcp_modules, trading_alerts, watchlist
    ):
        """Test daily portfolio monitoring workflow."""
        from app.mcp.resources.data import (
            get_current_watchlist,
            get_daily_stats,
            get_unread_alerts,
        )
        from app.mcp.tools.alerts import mark_alert_read

        # Step 1: Check daily stats
        stats = await get_daily_stats()
        assert "Daily Statistics" in stats
        assert "Unread:" in stats

        # Step 2: Review unread alerts
        unread = await get_unread_alerts()
        assert "Unread Alerts" in unread

        # Step 3: Mark alerts as reviewed
        unread_alert = next(a for a in trading_alerts if not a.is_read)
        mark_result = await mark_alert_read(unread_alert.id)
        assert "marked as read" in mark_result.lower()

        # Step 4: Check watchlist
        watchlist_status = await get_current_watchlist()
        assert "Watchlist" in watchlist_status


class TestRuleManagementWithAlerts:
    """Test rule management workflows that affect alerts."""

    @pytest.mark.asyncio
    async def test_analyze_rule_performance_workflow(
        self, patch_all_mcp_modules, trading_rules, trading_alerts
    ):
        """Test analyzing a rule's performance through its alerts."""
        from app.mcp.tools.alerts import get_alert_statistics
        from app.mcp.tools.rules import get_rule, list_rules

        # Step 1: List rules to find best performer
        rules = await list_rules()
        assert "High Volume Breakout" in rules
        assert "Alerts:" in rules  # Shows alert counts

        # Step 2: Get detailed rule info
        rule = next(r for r in trading_rules if r.name == "High Volume Breakout")
        rule_info = await get_rule(rule.id)
        assert "Alerts Triggered:" in rule_info

        # Step 3: Get overall statistics
        stats = await get_alert_statistics(days=30)
        assert "By Setup Type" in stats
        assert "BREAKOUT" in stats

    @pytest.mark.asyncio
    async def test_create_and_verify_rule_workflow(
        self, patch_all_mcp_modules
    ):
        """Test creating a rule and verifying it's properly set up."""
        from app.mcp.resources.data import get_active_rules
        from app.mcp.tools.rules import create_rule_from_description, get_rule, list_rules

        # Step 1: Create a new rule
        create_result = await create_rule_from_description(
            name="pre_market_gapper",
            description="Detects stocks with strong pre-market gaps",
            rule_type="gap",
            conditions="gap_percent >= 8 and pre_market_volume > 200000",
            stop_loss_percent=-4.0,
            target_percent=12.0,
            priority=18,
        )
        assert "Rule Created Successfully" in create_result

        # Step 2: Verify in rule list
        list_result = await list_rules()
        assert "pre_market_gapper" in list_result

        # Step 3: Check active rules resource
        active = await get_active_rules()
        assert "pre_market_gapper" in active


class TestWatchlistManagementWorkflow:
    """Test watchlist management workflows."""

    @pytest.mark.asyncio
    async def test_watchlist_cleanup_workflow(
        self, patch_all_mcp_modules, watchlist, trading_alerts
    ):
        """Test cleaning up watchlist based on analysis."""
        from app.mcp.tools.analysis import analyze_watchlist, get_symbol_analysis
        from app.mcp.tools.watchlist import get_watchlist, remove_from_watchlist

        # Step 1: Analyze watchlist
        analysis = await analyze_watchlist()
        assert "Watchlist Analysis" in analysis

        # Step 2: Check underperforming symbol
        # TSLA is inactive in our test data
        tsla_analysis = await get_symbol_analysis("TSLA")
        assert "TSLA Analysis" in tsla_analysis

        # Step 3: Remove from watchlist (it's already inactive, just verify removal works)
        remove_result = await remove_from_watchlist("TSLA")
        assert "Removed from Watchlist" in remove_result

        # Step 4: Verify updated watchlist
        updated = await get_watchlist()
        assert "TSLA" not in updated or "5 symbols" in updated

    @pytest.mark.asyncio
    async def test_symbol_comparison_for_selection(
        self, patch_all_mcp_modules, trading_alerts, watchlist
    ):
        """Test comparing symbols to make watchlist decisions."""
        from app.mcp.tools.analysis import compare_symbols, get_symbol_analysis
        from app.mcp.tools.watchlist import add_to_watchlist

        # Step 1: Compare potential adds
        comparison = await compare_symbols(["NVDA", "AMD", "SMCI"])
        assert "Symbol Comparison" in comparison
        assert "Most Active with High Confidence" in comparison

        # Step 2: Deep dive on top performer
        top_analysis = await get_symbol_analysis("NVDA")
        assert "NVDA Analysis" in top_analysis

        # Step 3: NVDA already in watchlist, try adding SMCI
        add_result = await add_to_watchlist("SMCI", notes="Added based on comparison analysis")
        assert "SMCI" in add_result


class TestDashboardViewWorkflow:
    """Test workflows that power dashboard views."""

    @pytest.mark.asyncio
    async def test_load_dashboard_data_workflow(
        self, patch_all_mcp_modules, trading_alerts, trading_rules, watchlist
    ):
        """Test loading all data needed for a dashboard view."""
        from app.mcp.resources.data import (
            get_active_rules,
            get_current_watchlist,
            get_daily_stats,
            get_recent_alerts,
            get_unread_alerts,
        )

        # Load all dashboard components
        stats = await get_daily_stats()
        recent = await get_recent_alerts()
        unread = await get_unread_alerts()
        rules = await get_active_rules()
        watchlist_data = await get_current_watchlist()

        # Verify all components loaded
        assert "Daily Statistics" in stats
        assert "Recent Alerts" in recent
        assert "Unread Alerts" in unread
        assert "Active Trading Rules" in rules
        assert "Watchlist" in watchlist_data

        # Cross-verify consistency
        # Stats should reflect alert counts from recent/unread
        assert "Today:" in stats
        assert "Unread:" in stats

    @pytest.mark.asyncio
    async def test_top_performers_to_analysis_workflow(
        self, patch_all_mcp_modules, trading_alerts
    ):
        """Test drilling from top performers into detailed analysis."""
        from app.mcp.tools.alerts import explain_alert
        from app.mcp.tools.analysis import get_symbol_analysis, get_top_performers

        # Step 1: Get top performers
        top = await get_top_performers(limit=3)
        assert "Top Performing Alerts" in top
        assert "NVDA" in top  # Highest confidence

        # Step 2: Analyze top symbol
        analysis = await get_symbol_analysis("NVDA")
        assert "NVDA Analysis" in analysis
        assert "Setup Distribution" in analysis

        # Step 3: Get detailed explanation of top alert
        nvda_alert = next(a for a in trading_alerts if a.symbol == "NVDA")
        explanation = await explain_alert(nvda_alert.id)
        assert "Alert #" in explanation
        assert "Risk/Reward" in explanation
