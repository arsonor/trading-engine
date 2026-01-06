"""Unit tests for the rule engine."""

import pytest

from app.engine.rule_engine import (
    ConfidenceModifier,
    OperatorType,
    RuleCondition,
    RuleConfidence,
    RuleDefinition,
    RuleEngine,
    RuleFilters,
    RuleTargets,
)


class TestOperatorType:
    """Tests for OperatorType enum."""

    def test_operator_values(self):
        """Test operator enum values."""
        assert OperatorType.GT.value == ">"
        assert OperatorType.GTE.value == ">="
        assert OperatorType.LT.value == "<"
        assert OperatorType.LTE.value == "<="
        assert OperatorType.EQ.value == "=="
        assert OperatorType.NEQ.value == "!="


class TestRuleCondition:
    """Tests for RuleCondition model."""

    def test_create_condition(self):
        """Test creating a rule condition."""
        condition = RuleCondition(
            field="price",
            operator=OperatorType.GT,
            value=100.0,
        )
        assert condition.field == "price"
        assert condition.operator == OperatorType.GT
        assert condition.value == 100.0

    def test_condition_with_string_value(self):
        """Test condition with reference value."""
        condition = RuleCondition(
            field="price",
            operator=OperatorType.GT,
            value="resistance_level",
        )
        assert condition.value == "resistance_level"


class TestRuleFilters:
    """Tests for RuleFilters model."""

    def test_empty_filters(self):
        """Test creating empty filters."""
        filters = RuleFilters()
        assert filters.min_price is None
        assert filters.max_price is None
        assert filters.min_volume is None
        assert filters.sectors is None

    def test_filters_with_values(self):
        """Test creating filters with values."""
        filters = RuleFilters(
            min_price=10.0,
            max_price=500.0,
            min_volume=100000,
            sectors=["technology", "healthcare"],
        )
        assert filters.min_price == 10.0
        assert filters.max_price == 500.0
        assert filters.min_volume == 100000
        assert filters.sectors == ["technology", "healthcare"]


class TestRuleTargets:
    """Tests for RuleTargets model."""

    def test_stop_loss_percent(self):
        """Test target with stop loss percent."""
        targets = RuleTargets(stop_loss_percent=-3.0, target_percent=6.0)
        assert targets.stop_loss_percent == -3.0
        assert targets.target_percent == 6.0

    def test_atr_multiplier(self):
        """Test target with ATR multiplier."""
        targets = RuleTargets(stop_loss_atr_multiplier=2.0, target_rr_ratio=3.0)
        assert targets.stop_loss_atr_multiplier == 2.0
        assert targets.target_rr_ratio == 3.0


class TestRuleConfidence:
    """Tests for RuleConfidence model."""

    def test_default_base_score(self):
        """Test default confidence base score."""
        confidence = RuleConfidence()
        assert confidence.base_score == 0.7
        assert confidence.modifiers is None

    def test_confidence_with_modifiers(self):
        """Test confidence with modifiers."""
        modifiers = [
            ConfidenceModifier(condition="volume_ratio > 2.0", adjustment=0.1),
            ConfidenceModifier(condition="rsi < 30", adjustment=0.05),
        ]
        confidence = RuleConfidence(base_score=0.6, modifiers=modifiers)
        assert confidence.base_score == 0.6
        assert len(confidence.modifiers) == 2


class TestRuleEngine:
    """Tests for RuleEngine class."""

    @pytest.fixture
    def engine(self) -> RuleEngine:
        """Create a rule engine instance."""
        return RuleEngine()

    @pytest.fixture
    def sample_rule(self) -> RuleDefinition:
        """Create a sample rule definition."""
        return RuleDefinition(
            name="Test Breakout",
            description="Test breakout rule",
            type="breakout",
            enabled=True,
            priority=10,
            conditions=[
                RuleCondition(field="price", operator=OperatorType.GT, value="resistance_level"),
                RuleCondition(field="volume_ratio", operator=OperatorType.GTE, value=1.5),
            ],
            filters=RuleFilters(min_price=5.0, max_price=500.0, min_volume=50000),
            targets=RuleTargets(stop_loss_percent=-3.0, target_rr_ratio=2.0),
            confidence=RuleConfidence(
                base_score=0.7,
                modifiers=[
                    ConfidenceModifier(condition="volume_ratio > 3.0", adjustment=0.15),
                ],
            ),
        )

    @pytest.fixture
    def market_data(self) -> dict:
        """Sample market data for testing."""
        return {
            "price": 150.0,
            "resistance_level": 145.0,
            "volume": 100000,
            "volume_ratio": 2.0,
            "atr": 3.5,
        }

    # ============== Initialization Tests ==============

    def test_init_empty(self, engine: RuleEngine):
        """Test engine initialization with no rules."""
        assert engine.rules == []

    def test_init_with_rules(self, sample_rule: RuleDefinition):
        """Test engine initialization with rules."""
        engine = RuleEngine(rules=[sample_rule])
        assert len(engine.rules) == 1
        assert engine.rules[0].name == "Test Breakout"

    def test_add_rule(self, engine: RuleEngine, sample_rule: RuleDefinition):
        """Test adding a rule to the engine."""
        engine.add_rule(sample_rule)
        assert len(engine.rules) == 1
        assert engine.rules[0].name == "Test Breakout"

    # ============== YAML Loading Tests ==============

    def test_load_rules_from_yaml(self, engine: RuleEngine):
        """Test loading rules from YAML string."""
        yaml_content = """
rules:
  - name: Test Rule
    type: breakout
    enabled: true
    priority: 5
    conditions:
      - field: price
        operator: ">"
        value: 100
"""
        engine.load_rules_from_yaml(yaml_content)
        assert len(engine.rules) == 1
        assert engine.rules[0].name == "Test Rule"
        assert engine.rules[0].type == "breakout"

    def test_load_rules_from_yaml_multiple(self, engine: RuleEngine):
        """Test loading multiple rules from YAML."""
        yaml_content = """
rules:
  - name: Rule 1
    type: breakout
    enabled: true
    priority: 10
    conditions:
      - field: price
        operator: ">"
        value: 100
  - name: Rule 2
    type: momentum
    enabled: false
    priority: 5
    conditions:
      - field: rsi
        operator: "<"
        value: 30
"""
        engine.load_rules_from_yaml(yaml_content)
        assert len(engine.rules) == 2
        assert engine.rules[0].name == "Rule 1"
        assert engine.rules[1].name == "Rule 2"

    # ============== Active Rules Tests ==============

    def test_get_active_rules_filters_disabled(self, engine: RuleEngine):
        """Test that disabled rules are filtered out."""
        enabled_rule = RuleDefinition(
            name="Enabled",
            type="breakout",
            enabled=True,
            priority=5,
            conditions=[RuleCondition(field="price", operator=OperatorType.GT, value=100)],
        )
        disabled_rule = RuleDefinition(
            name="Disabled",
            type="momentum",
            enabled=False,
            priority=10,
            conditions=[RuleCondition(field="rsi", operator=OperatorType.LT, value=30)],
        )
        engine.rules = [enabled_rule, disabled_rule]

        active = engine.get_active_rules()
        assert len(active) == 1
        assert active[0].name == "Enabled"

    def test_get_active_rules_sorted_by_priority(self, engine: RuleEngine):
        """Test that active rules are sorted by priority (descending)."""
        rule_low = RuleDefinition(
            name="Low Priority",
            type="a",
            enabled=True,
            priority=1,
            conditions=[RuleCondition(field="price", operator=OperatorType.GT, value=100)],
        )
        rule_high = RuleDefinition(
            name="High Priority",
            type="b",
            enabled=True,
            priority=10,
            conditions=[RuleCondition(field="price", operator=OperatorType.GT, value=100)],
        )
        rule_medium = RuleDefinition(
            name="Medium Priority",
            type="c",
            enabled=True,
            priority=5,
            conditions=[RuleCondition(field="price", operator=OperatorType.GT, value=100)],
        )
        engine.rules = [rule_low, rule_high, rule_medium]

        active = engine.get_active_rules()
        assert len(active) == 3
        assert active[0].name == "High Priority"
        assert active[1].name == "Medium Priority"
        assert active[2].name == "Low Priority"

    # ============== Condition Evaluation Tests ==============

    def test_evaluate_condition_gt_true(self, engine: RuleEngine, market_data: dict):
        """Test greater than condition - true case."""
        condition = RuleCondition(field="price", operator=OperatorType.GT, value=100.0)
        result = engine.evaluate_condition(condition, market_data)
        assert result is True

    def test_evaluate_condition_gt_false(self, engine: RuleEngine, market_data: dict):
        """Test greater than condition - false case."""
        condition = RuleCondition(field="price", operator=OperatorType.GT, value=200.0)
        result = engine.evaluate_condition(condition, market_data)
        assert result is False

    def test_evaluate_condition_gte(self, engine: RuleEngine, market_data: dict):
        """Test greater than or equal condition."""
        condition = RuleCondition(field="price", operator=OperatorType.GTE, value=150.0)
        result = engine.evaluate_condition(condition, market_data)
        assert result is True

    def test_evaluate_condition_lt(self, engine: RuleEngine, market_data: dict):
        """Test less than condition."""
        condition = RuleCondition(field="price", operator=OperatorType.LT, value=200.0)
        result = engine.evaluate_condition(condition, market_data)
        assert result is True

    def test_evaluate_condition_lte(self, engine: RuleEngine, market_data: dict):
        """Test less than or equal condition."""
        condition = RuleCondition(field="price", operator=OperatorType.LTE, value=150.0)
        result = engine.evaluate_condition(condition, market_data)
        assert result is True

    def test_evaluate_condition_eq(self, engine: RuleEngine, market_data: dict):
        """Test equal condition."""
        condition = RuleCondition(field="price", operator=OperatorType.EQ, value=150.0)
        result = engine.evaluate_condition(condition, market_data)
        assert result is True

    def test_evaluate_condition_neq(self, engine: RuleEngine, market_data: dict):
        """Test not equal condition."""
        condition = RuleCondition(field="price", operator=OperatorType.NEQ, value=100.0)
        result = engine.evaluate_condition(condition, market_data)
        assert result is True

    def test_evaluate_condition_reference_value(self, engine: RuleEngine, market_data: dict):
        """Test condition with reference value from market data."""
        condition = RuleCondition(
            field="price", operator=OperatorType.GT, value="resistance_level"
        )
        result = engine.evaluate_condition(condition, market_data)
        # price (150) > resistance_level (145)
        assert result is True

    def test_evaluate_condition_missing_field(self, engine: RuleEngine, market_data: dict):
        """Test condition with missing field returns False."""
        condition = RuleCondition(field="nonexistent", operator=OperatorType.GT, value=100.0)
        result = engine.evaluate_condition(condition, market_data)
        assert result is False

    def test_evaluate_condition_invalid_comparison(self, engine: RuleEngine):
        """Test condition with non-numeric values returns False."""
        condition = RuleCondition(field="symbol", operator=OperatorType.GT, value=100.0)
        market_data = {"symbol": "AAPL"}
        result = engine.evaluate_condition(condition, market_data)
        assert result is False

    # ============== Filter Tests ==============

    def test_check_filters_none(self, engine: RuleEngine, market_data: dict):
        """Test that None filters always pass."""
        result = engine.check_filters(None, market_data)
        assert result is True

    def test_check_filters_min_price_pass(self, engine: RuleEngine, market_data: dict):
        """Test min price filter - pass."""
        filters = RuleFilters(min_price=100.0)
        result = engine.check_filters(filters, market_data)
        assert result is True

    def test_check_filters_min_price_fail(self, engine: RuleEngine, market_data: dict):
        """Test min price filter - fail."""
        filters = RuleFilters(min_price=200.0)
        result = engine.check_filters(filters, market_data)
        assert result is False

    def test_check_filters_max_price_pass(self, engine: RuleEngine, market_data: dict):
        """Test max price filter - pass."""
        filters = RuleFilters(max_price=200.0)
        result = engine.check_filters(filters, market_data)
        assert result is True

    def test_check_filters_max_price_fail(self, engine: RuleEngine, market_data: dict):
        """Test max price filter - fail."""
        filters = RuleFilters(max_price=100.0)
        result = engine.check_filters(filters, market_data)
        assert result is False

    def test_check_filters_min_volume_pass(self, engine: RuleEngine, market_data: dict):
        """Test min volume filter - pass."""
        filters = RuleFilters(min_volume=50000)
        result = engine.check_filters(filters, market_data)
        assert result is True

    def test_check_filters_min_volume_fail(self, engine: RuleEngine, market_data: dict):
        """Test min volume filter - fail."""
        filters = RuleFilters(min_volume=200000)
        result = engine.check_filters(filters, market_data)
        assert result is False

    def test_check_filters_combined(self, engine: RuleEngine, market_data: dict):
        """Test multiple filters combined."""
        filters = RuleFilters(min_price=100.0, max_price=200.0, min_volume=50000)
        result = engine.check_filters(filters, market_data)
        assert result is True

    # ============== Target Calculation Tests ==============

    def test_calculate_targets_none(self, engine: RuleEngine, market_data: dict):
        """Test target calculation with no targets."""
        result = engine.calculate_targets(100.0, None, market_data)
        assert result["stop_loss"] is None
        assert result["target_price"] is None

    def test_calculate_targets_stop_loss_percent(self, engine: RuleEngine, market_data: dict):
        """Test stop loss calculation with percentage."""
        targets = RuleTargets(stop_loss_percent=-3.0)
        result = engine.calculate_targets(100.0, targets, market_data)
        assert result["stop_loss"] == 97.0  # 100 * (1 + (-3/100)) = 97

    def test_calculate_targets_stop_loss_atr(self, engine: RuleEngine, market_data: dict):
        """Test stop loss calculation with ATR multiplier."""
        targets = RuleTargets(stop_loss_atr_multiplier=2.0)
        result = engine.calculate_targets(100.0, targets, market_data)
        # 100 - (3.5 * 2.0) = 93.0
        assert result["stop_loss"] == 93.0

    def test_calculate_targets_target_percent(self, engine: RuleEngine, market_data: dict):
        """Test target price calculation with percentage."""
        targets = RuleTargets(target_percent=6.0)
        result = engine.calculate_targets(100.0, targets, market_data)
        assert result["target_price"] == 106.0  # 100 * (1 + 6/100) = 106

    def test_calculate_targets_target_rr_ratio(self, engine: RuleEngine, market_data: dict):
        """Test target price calculation with risk/reward ratio."""
        targets = RuleTargets(stop_loss_percent=-3.0, target_rr_ratio=2.0)
        result = engine.calculate_targets(100.0, targets, market_data)
        # stop_loss = 97, risk = 100 - 97 = 3
        # target = 100 + (3 * 2.0) = 106
        assert result["stop_loss"] == 97.0
        assert result["target_price"] == 106.0

    # ============== Confidence Calculation Tests ==============

    def test_calculate_confidence_none(self, engine: RuleEngine, market_data: dict):
        """Test confidence calculation with no config returns default."""
        result = engine.calculate_confidence(None, market_data)
        assert result == 0.7

    def test_calculate_confidence_base_score(self, engine: RuleEngine, market_data: dict):
        """Test confidence calculation with base score only."""
        confidence = RuleConfidence(base_score=0.6)
        result = engine.calculate_confidence(confidence, market_data)
        assert result == 0.6

    def test_calculate_confidence_with_modifiers(self, engine: RuleEngine, market_data: dict):
        """Test confidence calculation with modifiers."""
        confidence = RuleConfidence(
            base_score=0.6,
            modifiers=[
                ConfidenceModifier(condition="volume_ratio > 1.5", adjustment=0.1),
            ],
        )
        result = engine.calculate_confidence(confidence, market_data)
        # volume_ratio (2.0) > 1.5, so modifier applies
        assert result == 0.7

    def test_calculate_confidence_modifier_not_triggered(
        self, engine: RuleEngine, market_data: dict
    ):
        """Test confidence when modifier condition is not met."""
        confidence = RuleConfidence(
            base_score=0.6,
            modifiers=[
                ConfidenceModifier(condition="volume_ratio > 5.0", adjustment=0.2),
            ],
        )
        result = engine.calculate_confidence(confidence, market_data)
        # volume_ratio (2.0) is not > 5.0, so no adjustment
        assert result == 0.6

    def test_calculate_confidence_clamped_max(self, engine: RuleEngine, market_data: dict):
        """Test confidence is clamped to maximum 1.0."""
        confidence = RuleConfidence(
            base_score=0.9,
            modifiers=[
                ConfidenceModifier(condition="volume_ratio > 1.0", adjustment=0.5),
            ],
        )
        result = engine.calculate_confidence(confidence, market_data)
        assert result == 1.0

    def test_calculate_confidence_clamped_min(self, engine: RuleEngine, market_data: dict):
        """Test confidence is clamped to minimum 0.0."""
        confidence = RuleConfidence(
            base_score=0.1,
            modifiers=[
                ConfidenceModifier(condition="volume_ratio > 1.0", adjustment=-0.5),
            ],
        )
        result = engine.calculate_confidence(confidence, market_data)
        assert result == 0.0

    # ============== Rule Evaluation Tests ==============

    def test_evaluate_rule_disabled(
        self, engine: RuleEngine, sample_rule: RuleDefinition, market_data: dict
    ):
        """Test that disabled rules are not triggered."""
        sample_rule.enabled = False
        result = engine.evaluate_rule(sample_rule, market_data)
        assert result.triggered is False

    def test_evaluate_rule_filters_fail(
        self, engine: RuleEngine, sample_rule: RuleDefinition, market_data: dict
    ):
        """Test rule fails when filters don't pass."""
        sample_rule.filters = RuleFilters(min_price=1000.0)  # Price won't pass
        result = engine.evaluate_rule(sample_rule, market_data)
        assert result.triggered is False

    def test_evaluate_rule_conditions_not_met(self, engine: RuleEngine, market_data: dict):
        """Test rule when conditions are not met."""
        rule = RuleDefinition(
            name="Won't Trigger",
            type="test",
            enabled=True,
            priority=1,
            conditions=[
                RuleCondition(field="price", operator=OperatorType.GT, value=1000.0),
            ],
        )
        result = engine.evaluate_rule(rule, market_data)
        assert result.triggered is False

    def test_evaluate_rule_success(
        self, engine: RuleEngine, sample_rule: RuleDefinition, market_data: dict
    ):
        """Test successful rule evaluation."""
        result = engine.evaluate_rule(sample_rule, market_data)
        assert result.triggered is True
        assert result.rule_name == "Test Breakout"
        assert result.entry_price == 150.0
        assert result.stop_loss is not None
        assert result.target_price is not None
        assert result.confidence > 0
        assert len(result.matched_conditions) == 2

    # ============== Evaluate All Rules Tests ==============

    def test_evaluate_all_rules_empty(self, engine: RuleEngine, market_data: dict):
        """Test evaluating empty rule set."""
        results = engine.evaluate_all_rules(market_data)
        assert results == []

    def test_evaluate_all_rules_none_triggered(self, engine: RuleEngine, market_data: dict):
        """Test when no rules are triggered."""
        rule = RuleDefinition(
            name="Won't Trigger",
            type="test",
            enabled=True,
            priority=1,
            conditions=[
                RuleCondition(field="price", operator=OperatorType.GT, value=1000.0),
            ],
        )
        engine.add_rule(rule)
        results = engine.evaluate_all_rules(market_data)
        assert results == []

    def test_evaluate_all_rules_one_triggered(
        self, engine: RuleEngine, sample_rule: RuleDefinition, market_data: dict
    ):
        """Test when one rule is triggered."""
        engine.add_rule(sample_rule)
        results = engine.evaluate_all_rules(market_data)
        assert len(results) == 1
        assert results[0].rule_name == "Test Breakout"

    def test_evaluate_all_rules_multiple(self, engine: RuleEngine, market_data: dict):
        """Test evaluating multiple rules."""
        rule1 = RuleDefinition(
            name="Rule 1",
            type="test1",
            enabled=True,
            priority=10,
            conditions=[
                RuleCondition(field="price", operator=OperatorType.GT, value=100.0),
            ],
        )
        rule2 = RuleDefinition(
            name="Rule 2",
            type="test2",
            enabled=True,
            priority=5,
            conditions=[
                RuleCondition(field="volume", operator=OperatorType.GTE, value=50000),
            ],
        )
        rule3 = RuleDefinition(
            name="Rule 3 - Won't trigger",
            type="test3",
            enabled=True,
            priority=1,
            conditions=[
                RuleCondition(field="price", operator=OperatorType.LT, value=50.0),
            ],
        )
        engine.rules = [rule1, rule2, rule3]

        results = engine.evaluate_all_rules(market_data)
        assert len(results) == 2
        # Results should be in priority order (high to low)
        assert results[0].rule_name == "Rule 1"
        assert results[1].rule_name == "Rule 2"


class TestModifierConditionEvaluation:
    """Tests for the private _evaluate_modifier_condition method."""

    @pytest.fixture
    def engine(self) -> RuleEngine:
        """Create a rule engine instance."""
        return RuleEngine()

    def test_valid_condition(self, engine: RuleEngine):
        """Test valid modifier condition."""
        market_data = {"volume_ratio": 3.5}
        result = engine._evaluate_modifier_condition("volume_ratio > 3.0", market_data)
        assert result is True

    def test_condition_not_met(self, engine: RuleEngine):
        """Test modifier condition not met."""
        market_data = {"volume_ratio": 2.0}
        result = engine._evaluate_modifier_condition("volume_ratio > 3.0", market_data)
        assert result is False

    def test_invalid_format(self, engine: RuleEngine):
        """Test invalid condition format."""
        market_data = {"volume_ratio": 3.5}
        result = engine._evaluate_modifier_condition("invalid condition format here", market_data)
        assert result is False

    def test_missing_field(self, engine: RuleEngine):
        """Test condition with missing field."""
        market_data = {"price": 100}
        result = engine._evaluate_modifier_condition("volume_ratio > 3.0", market_data)
        assert result is False

    def test_all_operators(self, engine: RuleEngine):
        """Test all supported operators in modifier conditions."""
        market_data = {"value": 5.0}

        assert engine._evaluate_modifier_condition("value > 4.0", market_data) is True
        assert engine._evaluate_modifier_condition("value >= 5.0", market_data) is True
        assert engine._evaluate_modifier_condition("value < 6.0", market_data) is True
        assert engine._evaluate_modifier_condition("value <= 5.0", market_data) is True
        assert engine._evaluate_modifier_condition("value == 5.0", market_data) is True
        assert engine._evaluate_modifier_condition("value != 4.0", market_data) is True

    def test_invalid_operator(self, engine: RuleEngine):
        """Test invalid operator in condition."""
        market_data = {"value": 5.0}
        result = engine._evaluate_modifier_condition("value <> 4.0", market_data)
        assert result is False
