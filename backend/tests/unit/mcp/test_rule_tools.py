"""Unit tests for MCP rule tools."""

from unittest.mock import patch

import pytest

from app.models.rule import Rule


class TestListRules:
    """Tests for list_rules tool."""

    @pytest.mark.asyncio
    async def test_list_all_rules(
        self, mock_get_db_session, mcp_sample_rule, mcp_inactive_rule
    ):
        """Test listing all rules."""
        with patch("app.mcp.tools.rules.get_db_session", mock_get_db_session):
            from app.mcp.tools.rules import list_rules

            result = await list_rules()

            assert "Trading Rules" in result
            assert "2 total" in result
            assert mcp_sample_rule.name in result
            assert mcp_inactive_rule.name in result
            assert "✅" in result  # Active rule indicator
            assert "❌" in result  # Inactive rule indicator

    @pytest.mark.asyncio
    async def test_list_active_only(
        self, mock_get_db_session, mcp_sample_rule, mcp_inactive_rule
    ):
        """Test listing only active rules."""
        with patch("app.mcp.tools.rules.get_db_session", mock_get_db_session):
            from app.mcp.tools.rules import list_rules

            result = await list_rules(active_only=True)

            assert mcp_sample_rule.name in result
            assert mcp_inactive_rule.name not in result

    @pytest.mark.asyncio
    async def test_list_rules_empty(self, mock_get_db_session):
        """Test listing rules when none exist."""
        with patch("app.mcp.tools.rules.get_db_session", mock_get_db_session):
            from app.mcp.tools.rules import list_rules

            result = await list_rules()

            assert "No rules found" in result

    @pytest.mark.asyncio
    async def test_list_rules_shows_alert_count(
        self, mock_get_db_session, mcp_sample_alert, mcp_sample_rule
    ):
        """Test that rules list shows alert counts."""
        with patch("app.mcp.tools.rules.get_db_session", mock_get_db_session):
            from app.mcp.tools.rules import list_rules

            result = await list_rules()

            assert "Alerts:" in result
            # The sample rule should have at least 1 alert
            assert "1" in result or "Alerts: 1" in result


class TestGetRule:
    """Tests for get_rule tool."""

    @pytest.mark.asyncio
    async def test_get_existing_rule(self, mock_get_db_session, mcp_sample_rule):
        """Test getting an existing rule by ID."""
        with patch("app.mcp.tools.rules.get_db_session", mock_get_db_session):
            from app.mcp.tools.rules import get_rule

            result = await get_rule(mcp_sample_rule.id)

            assert f"Rule #{mcp_sample_rule.id}" in result
            assert mcp_sample_rule.name in result
            assert "Active" in result
            assert "price" in result  # rule_type
            assert "Configuration" in result
            assert "YAML" in result

    @pytest.mark.asyncio
    async def test_get_nonexistent_rule(self, mock_get_db_session):
        """Test getting a non-existent rule returns appropriate message."""
        with patch("app.mcp.tools.rules.get_db_session", mock_get_db_session):
            from app.mcp.tools.rules import get_rule

            result = await get_rule(99999)

            assert "not found" in result.lower()
            assert "99999" in result

    @pytest.mark.asyncio
    async def test_get_rule_includes_description(
        self, mock_get_db_session, mcp_sample_rule
    ):
        """Test that rule details include description."""
        with patch("app.mcp.tools.rules.get_db_session", mock_get_db_session):
            from app.mcp.tools.rules import get_rule

            result = await get_rule(mcp_sample_rule.id)

            assert "Description" in result
            assert mcp_sample_rule.description in result

    @pytest.mark.asyncio
    async def test_get_rule_includes_metadata(
        self, mock_get_db_session, mcp_sample_rule
    ):
        """Test that rule details include creation metadata."""
        with patch("app.mcp.tools.rules.get_db_session", mock_get_db_session):
            from app.mcp.tools.rules import get_rule

            result = await get_rule(mcp_sample_rule.id)

            assert "Created" in result
            assert "Updated" in result


class TestCreateRuleFromDescription:
    """Tests for create_rule_from_description tool."""

    @pytest.mark.asyncio
    async def test_create_simple_rule(self, mock_get_db_session):
        """Test creating a rule with simple conditions."""
        with patch("app.mcp.tools.rules.get_db_session", mock_get_db_session):
            from app.mcp.tools.rules import create_rule_from_description

            result = await create_rule_from_description(
                name="test_volume_rule",
                description="Alert on high volume",
                rule_type="volume",
                conditions="volume_ratio > 2.0",
            )

            assert "Rule Created Successfully" in result
            assert "test_volume_rule" in result
            assert "volume" in result
            assert "Active" in result

    @pytest.mark.asyncio
    async def test_create_rule_with_multiple_conditions(self, mock_get_db_session):
        """Test creating a rule with multiple conditions."""
        with patch("app.mcp.tools.rules.get_db_session", mock_get_db_session):
            from app.mcp.tools.rules import create_rule_from_description

            result = await create_rule_from_description(
                name="multi_condition_rule",
                description="Complex rule with multiple conditions",
                rule_type="price",
                conditions="price_change_percent > 5 and volume_ratio >= 1.5",
            )

            assert "Rule Created Successfully" in result
            assert "multi_condition_rule" in result
            assert "price_change_percent" in result
            assert "volume_ratio" in result

    @pytest.mark.asyncio
    async def test_create_rule_with_custom_targets(self, mock_get_db_session):
        """Test creating a rule with custom stop loss and target."""
        with patch("app.mcp.tools.rules.get_db_session", mock_get_db_session):
            from app.mcp.tools.rules import create_rule_from_description

            result = await create_rule_from_description(
                name="custom_target_rule",
                description="Rule with custom risk management",
                rule_type="price",
                conditions="price > 100",
                stop_loss_percent=-5.0,
                target_percent=10.0,
            )

            assert "Rule Created Successfully" in result
            assert "-5.0" in result
            assert "10.0" in result

    @pytest.mark.asyncio
    async def test_create_rule_invalid_type(self, mock_get_db_session):
        """Test creating a rule with invalid type returns error."""
        with patch("app.mcp.tools.rules.get_db_session", mock_get_db_session):
            from app.mcp.tools.rules import create_rule_from_description

            result = await create_rule_from_description(
                name="invalid_type_rule",
                description="This should fail",
                rule_type="invalid_type",
                conditions="price > 100",
            )

            assert "Invalid rule_type" in result
            assert "invalid_type" in result

    @pytest.mark.asyncio
    async def test_create_rule_duplicate_name(
        self, mock_get_db_session, mcp_sample_rule
    ):
        """Test creating a rule with duplicate name returns error."""
        with patch("app.mcp.tools.rules.get_db_session", mock_get_db_session):
            from app.mcp.tools.rules import create_rule_from_description

            result = await create_rule_from_description(
                name=mcp_sample_rule.name,  # Use existing name
                description="Duplicate test",
                rule_type="price",
                conditions="price > 100",
            )

            assert "already exists" in result

    @pytest.mark.asyncio
    async def test_create_rule_invalid_conditions(self, mock_get_db_session):
        """Test creating a rule with unparseable conditions returns error."""
        with patch("app.mcp.tools.rules.get_db_session", mock_get_db_session):
            from app.mcp.tools.rules import create_rule_from_description

            result = await create_rule_from_description(
                name="bad_conditions_rule",
                description="This should fail",
                rule_type="price",
                conditions="this is not valid condition syntax",
            )

            assert "Could not parse conditions" in result


class TestToggleRule:
    """Tests for toggle_rule tool."""

    @pytest.mark.asyncio
    async def test_toggle_active_to_inactive(
        self, mock_get_db_session, mcp_sample_rule
    ):
        """Test toggling an active rule to inactive."""
        assert mcp_sample_rule.is_active is True

        with patch("app.mcp.tools.rules.get_db_session", mock_get_db_session):
            from app.mcp.tools.rules import toggle_rule

            result = await toggle_rule(mcp_sample_rule.id)

            assert "toggled" in result.lower()
            assert "Active" in result  # Previous status
            assert "Inactive" in result  # New status
            assert "❌" in result  # Inactive indicator

    @pytest.mark.asyncio
    async def test_toggle_inactive_to_active(
        self, mock_get_db_session, mcp_inactive_rule
    ):
        """Test toggling an inactive rule to active."""
        assert mcp_inactive_rule.is_active is False

        with patch("app.mcp.tools.rules.get_db_session", mock_get_db_session):
            from app.mcp.tools.rules import toggle_rule

            result = await toggle_rule(mcp_inactive_rule.id)

            assert "toggled" in result.lower()
            assert "Inactive" in result  # Previous status
            assert "Active" in result  # New status
            assert "✅" in result  # Active indicator

    @pytest.mark.asyncio
    async def test_toggle_nonexistent_rule(self, mock_get_db_session):
        """Test toggling a non-existent rule returns appropriate message."""
        with patch("app.mcp.tools.rules.get_db_session", mock_get_db_session):
            from app.mcp.tools.rules import toggle_rule

            result = await toggle_rule(99999)

            assert "not found" in result.lower()
            assert "99999" in result


class TestDeleteRule:
    """Tests for delete_rule tool."""

    @pytest.mark.asyncio
    async def test_delete_existing_rule(self, mock_get_db_session, mcp_inactive_rule):
        """Test deleting an existing rule."""
        with patch("app.mcp.tools.rules.get_db_session", mock_get_db_session):
            from app.mcp.tools.rules import delete_rule

            result = await delete_rule(mcp_inactive_rule.id)

            assert "Rule Deleted" in result
            assert mcp_inactive_rule.name in result

    @pytest.mark.asyncio
    async def test_delete_rule_with_alerts(
        self, mock_get_db_session, mcp_sample_rule, mcp_sample_alert
    ):
        """Test deleting a rule that has associated alerts."""
        with patch("app.mcp.tools.rules.get_db_session", mock_get_db_session):
            from app.mcp.tools.rules import delete_rule

            result = await delete_rule(mcp_sample_rule.id)

            assert "Rule Deleted" in result
            assert "alert" in result.lower()  # Should mention alerts

    @pytest.mark.asyncio
    async def test_delete_nonexistent_rule(self, mock_get_db_session):
        """Test deleting a non-existent rule returns appropriate message."""
        with patch("app.mcp.tools.rules.get_db_session", mock_get_db_session):
            from app.mcp.tools.rules import delete_rule

            result = await delete_rule(99999)

            assert "not found" in result.lower()
            assert "99999" in result


class TestParseConditions:
    """Tests for _parse_conditions helper function."""

    def test_parse_simple_condition(self):
        """Test parsing a simple condition."""
        from app.mcp.tools.rules import _parse_conditions

        result = _parse_conditions("volume_ratio > 2.0")

        assert len(result) == 1
        assert result[0]["field"] == "volume_ratio"
        assert result[0]["operator"] == ">"
        assert result[0]["value"] == 2.0

    def test_parse_multiple_conditions(self):
        """Test parsing multiple conditions with 'and'."""
        from app.mcp.tools.rules import _parse_conditions

        result = _parse_conditions("price > 100 and volume > 1000000")

        assert len(result) == 2
        assert result[0]["field"] == "price"
        assert result[1]["field"] == "volume"

    def test_parse_various_operators(self):
        """Test parsing different comparison operators."""
        from app.mcp.tools.rules import _parse_conditions

        test_cases = [
            ("field >= 10", ">="),
            ("field <= 10", "<="),
            ("field == 10", "="),
            ("field != 10", "!="),
        ]

        for condition, expected_op in test_cases:
            result = _parse_conditions(condition)
            assert result[0]["operator"] == expected_op

    def test_parse_integer_value(self):
        """Test parsing integer values."""
        from app.mcp.tools.rules import _parse_conditions

        result = _parse_conditions("count > 100")

        assert result[0]["value"] == 100
        assert isinstance(result[0]["value"], int)

    def test_parse_float_value(self):
        """Test parsing float values."""
        from app.mcp.tools.rules import _parse_conditions

        result = _parse_conditions("ratio > 1.5")

        assert result[0]["value"] == 1.5
        assert isinstance(result[0]["value"], float)

    def test_parse_empty_returns_empty_list(self):
        """Test parsing empty or invalid string returns empty list."""
        from app.mcp.tools.rules import _parse_conditions

        result = _parse_conditions("no valid conditions here")

        assert result == []
