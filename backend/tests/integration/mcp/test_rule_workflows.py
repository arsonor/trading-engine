"""Integration tests for MCP rule management workflows.

These tests verify complete rule management workflows through MCP tools.
"""

import pytest


class TestRuleManagementWorkflow:
    """Test complete rule management workflows."""

    @pytest.mark.asyncio
    async def test_list_and_get_rule_details(
        self, patch_all_mcp_modules, trading_rules, trading_alerts
    ):
        """Test listing rules and getting detailed information."""
        from app.mcp.tools.rules import get_rule, list_rules

        # List all rules
        list_result = await list_rules()

        assert "Trading Rules" in list_result
        assert "4 total" in list_result
        assert "High Volume Breakout" in list_result
        assert "Gap Up Scanner" in list_result
        assert "✅" in list_result  # Active indicator
        assert "❌" in list_result  # Inactive indicator

        # Get details for the first rule
        breakout_rule = next(r for r in trading_rules if r.name == "High Volume Breakout")
        detail_result = await get_rule(breakout_rule.id)

        assert f"Rule #{breakout_rule.id}" in detail_result
        assert "High Volume Breakout" in detail_result
        assert "Active" in detail_result
        assert "price" in detail_result  # rule_type
        assert "Configuration" in detail_result
        assert "YAML" in detail_result

    @pytest.mark.asyncio
    async def test_list_active_only_rules(
        self, patch_all_mcp_modules, trading_rules
    ):
        """Test filtering to show only active rules."""
        from app.mcp.tools.rules import list_rules

        result = await list_rules(active_only=True)

        assert "Trading Rules" in result
        assert "3 total" in result  # 3 active rules
        assert "High Volume Breakout" in result
        assert "Disabled Test Rule" not in result

    @pytest.mark.asyncio
    async def test_create_rule_workflow(self, patch_all_mcp_modules):
        """Test creating a new rule from description."""
        from app.mcp.tools.rules import create_rule_from_description, get_rule, list_rules

        # Create a new rule
        create_result = await create_rule_from_description(
            name="momentum_surge_detector",
            description="Detects strong momentum moves with volume confirmation",
            rule_type="price",
            conditions="price_change_percent > 4 and volume_ratio >= 2.0",
            stop_loss_percent=-2.5,
            target_percent=7.5,
            priority=15,
        )

        assert "Rule Created Successfully" in create_result
        assert "momentum_surge_detector" in create_result
        assert "Active" in create_result
        assert "price_change_percent" in create_result
        assert "volume_ratio" in create_result

        # Verify it appears in the list
        list_result = await list_rules()
        assert "momentum_surge_detector" in list_result

    @pytest.mark.asyncio
    async def test_toggle_rule_workflow(
        self, patch_all_mcp_modules, trading_rules
    ):
        """Test toggling rules on and off."""
        from app.mcp.tools.rules import list_rules, toggle_rule

        # Get an active rule
        active_rule = next(r for r in trading_rules if r.is_active)

        # Toggle it off
        toggle_result = await toggle_rule(active_rule.id)

        assert "toggled" in toggle_result.lower()
        assert "Active" in toggle_result  # Previous status
        assert "Inactive" in toggle_result  # New status
        assert "❌" in toggle_result

        # Verify in list
        list_result = await list_rules(active_only=True)
        # Should have one less active rule now
        assert "2 total" in list_result

        # Toggle it back on
        toggle_back = await toggle_rule(active_rule.id)
        assert "Active" in toggle_back
        assert "✅" in toggle_back

    @pytest.mark.asyncio
    async def test_delete_rule_workflow(
        self, patch_all_mcp_modules, trading_rules, trading_alerts
    ):
        """Test deleting a rule and verifying alert preservation."""
        from app.mcp.tools.rules import delete_rule, list_rules

        # Delete the disabled rule (has no alerts)
        disabled_rule = next(r for r in trading_rules if not r.is_active)
        delete_result = await delete_rule(disabled_rule.id)

        assert "Rule Deleted" in delete_result
        assert "Disabled Test Rule" in delete_result
        assert "No alerts were associated" in delete_result

        # Verify it's gone from list
        list_result = await list_rules()
        assert "3 total" in list_result
        assert "Disabled Test Rule" not in list_result

    @pytest.mark.asyncio
    async def test_delete_rule_with_alerts(
        self, patch_all_mcp_modules, trading_rules, trading_alerts
    ):
        """Test deleting a rule that has associated alerts."""
        from app.mcp.tools.rules import delete_rule

        # Delete the High Volume Breakout rule (has multiple alerts)
        breakout_rule = next(r for r in trading_rules if r.name == "High Volume Breakout")
        delete_result = await delete_rule(breakout_rule.id)

        assert "Rule Deleted" in delete_result
        assert "High Volume Breakout" in delete_result
        assert "alert" in delete_result.lower()
        assert "preserved" in delete_result


class TestRuleResourcesIntegration:
    """Test MCP resources for rules."""

    @pytest.mark.asyncio
    async def test_active_rules_resource(
        self, patch_all_mcp_modules, trading_rules, trading_alerts
    ):
        """Test rules://active resource."""
        from app.mcp.resources.data import get_active_rules

        result = await get_active_rules()

        assert "Active Trading Rules" in result
        assert "3" in result  # 3 active rules
        assert "High Volume Breakout" in result
        assert "Gap Up Scanner" in result
        assert "Volume Spike Alert" in result
        assert "Disabled Test Rule" not in result
        assert "Alerts:" in result  # Should show alert counts

    @pytest.mark.asyncio
    async def test_active_rules_shows_priority_order(
        self, patch_all_mcp_modules, trading_rules
    ):
        """Test that active rules are ordered by priority."""
        from app.mcp.resources.data import get_active_rules

        result = await get_active_rules()

        # High Volume Breakout has priority 20, should come first
        # Check order in result
        high_vol_pos = result.find("High Volume Breakout")
        gap_up_pos = result.find("Gap Up Scanner")
        vol_spike_pos = result.find("Volume Spike Alert")

        assert high_vol_pos < gap_up_pos < vol_spike_pos


class TestRuleCreationValidation:
    """Test rule creation validation scenarios."""

    @pytest.mark.asyncio
    async def test_create_rule_invalid_type(self, patch_all_mcp_modules):
        """Test creating rule with invalid type returns error."""
        from app.mcp.tools.rules import create_rule_from_description

        result = await create_rule_from_description(
            name="invalid_rule",
            description="Test invalid type",
            rule_type="invalid",
            conditions="price > 100",
        )

        assert "Invalid rule_type" in result

    @pytest.mark.asyncio
    async def test_create_rule_duplicate_name(
        self, patch_all_mcp_modules, trading_rules
    ):
        """Test creating rule with duplicate name returns error."""
        from app.mcp.tools.rules import create_rule_from_description

        result = await create_rule_from_description(
            name="High Volume Breakout",  # Already exists
            description="Duplicate test",
            rule_type="price",
            conditions="price > 100",
        )

        assert "already exists" in result

    @pytest.mark.asyncio
    async def test_create_rule_invalid_conditions(self, patch_all_mcp_modules):
        """Test creating rule with unparseable conditions."""
        from app.mcp.tools.rules import create_rule_from_description

        result = await create_rule_from_description(
            name="bad_conditions_rule",
            description="Test bad conditions",
            rule_type="price",
            conditions="this makes no sense as a condition",
        )

        assert "Could not parse conditions" in result
