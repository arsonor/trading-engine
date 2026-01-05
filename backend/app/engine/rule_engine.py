"""Rule evaluation engine."""

import operator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field


class OperatorType(str, Enum):
    """Supported comparison operators."""

    GT = ">"
    GTE = ">="
    LT = "<"
    LTE = "<="
    EQ = "=="
    NEQ = "!="


class RuleCondition(BaseModel):
    """A single condition in a rule."""

    field: str
    operator: OperatorType
    value: Any


class RuleFilters(BaseModel):
    """Filters to apply before rule evaluation."""

    min_price: Optional[float] = None
    max_price: Optional[float] = None
    min_volume: Optional[int] = None
    sectors: Optional[List[str]] = None


class RuleTargets(BaseModel):
    """Target price calculations."""

    stop_loss_percent: Optional[float] = None
    stop_loss_atr_multiplier: Optional[float] = None
    target_percent: Optional[float] = None
    target_rr_ratio: Optional[float] = None


class ConfidenceModifier(BaseModel):
    """Confidence score modifier."""

    condition: str
    adjustment: float


class RuleConfidence(BaseModel):
    """Confidence calculation settings."""

    base_score: float = Field(default=0.7, ge=0.0, le=1.0)
    modifiers: Optional[List[ConfidenceModifier]] = None


class RuleDefinition(BaseModel):
    """Complete rule definition."""

    name: str
    description: Optional[str] = None
    type: str
    enabled: bool = True
    priority: int = 0
    conditions: List[RuleCondition]
    filters: Optional[RuleFilters] = None
    targets: Optional[RuleTargets] = None
    confidence: Optional[RuleConfidence] = None
    lookback_periods: Optional[Dict[str, int]] = None
    time_window: Optional[Dict[str, str]] = None


class RulesConfig(BaseModel):
    """Rules configuration file structure."""

    rules: List[RuleDefinition]


@dataclass
class RuleEvaluationResult:
    """Result of evaluating a rule against market data."""

    triggered: bool
    rule_name: str
    confidence: float = 0.0
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None
    matched_conditions: List[str] = field(default_factory=list)


class RuleEngine:
    """Engine for evaluating trading rules against market data."""

    # Operator mapping
    OPERATORS: Dict[OperatorType, Callable] = {
        OperatorType.GT: operator.gt,
        OperatorType.GTE: operator.ge,
        OperatorType.LT: operator.lt,
        OperatorType.LTE: operator.le,
        OperatorType.EQ: operator.eq,
        OperatorType.NEQ: operator.ne,
    }

    def __init__(self, rules: List[RuleDefinition] = None):
        """Initialize rule engine with optional rules."""
        self.rules = rules or []

    def load_rules_from_yaml(self, yaml_content: str) -> None:
        """Load rules from YAML string."""
        parsed = yaml.safe_load(yaml_content)
        config = RulesConfig(**parsed)
        self.rules = config.rules

    def load_rules_from_file(self, file_path: str) -> None:
        """Load rules from YAML file."""
        with open(file_path, "r") as f:
            self.load_rules_from_yaml(f.read())

    def add_rule(self, rule: RuleDefinition) -> None:
        """Add a rule to the engine."""
        self.rules.append(rule)

    def get_active_rules(self) -> List[RuleDefinition]:
        """Get all active rules sorted by priority."""
        active = [r for r in self.rules if r.enabled]
        return sorted(active, key=lambda r: r.priority, reverse=True)

    def evaluate_condition(
        self, condition: RuleCondition, market_data: Dict[str, Any]
    ) -> bool:
        """Evaluate a single condition against market data."""
        field_value = market_data.get(condition.field)
        if field_value is None:
            return False

        compare_value = condition.value

        # Handle reference values (e.g., "resistance_level", "sma_20")
        if isinstance(compare_value, str) and compare_value in market_data:
            compare_value = market_data[compare_value]

        # Get operator function
        op_func = self.OPERATORS.get(condition.operator)
        if op_func is None:
            return False

        try:
            return op_func(float(field_value), float(compare_value))
        except (ValueError, TypeError):
            return False

    def check_filters(
        self, filters: Optional[RuleFilters], market_data: Dict[str, Any]
    ) -> bool:
        """Check if market data passes all filters."""
        if filters is None:
            return True

        price = market_data.get("price", 0)
        volume = market_data.get("volume", 0)

        if filters.min_price and price < filters.min_price:
            return False
        if filters.max_price and price > filters.max_price:
            return False
        if filters.min_volume and volume < filters.min_volume:
            return False

        return True

    def calculate_targets(
        self,
        entry_price: float,
        targets: Optional[RuleTargets],
        market_data: Dict[str, Any],
    ) -> Dict[str, Optional[float]]:
        """Calculate stop loss and target prices."""
        result = {"stop_loss": None, "target_price": None}

        if targets is None:
            return result

        # Calculate stop loss
        if targets.stop_loss_percent:
            result["stop_loss"] = round(
                entry_price * (1 + targets.stop_loss_percent / 100), 2
            )
        elif targets.stop_loss_atr_multiplier:
            atr = market_data.get("atr", 0)
            if atr:
                result["stop_loss"] = round(
                    entry_price - (atr * targets.stop_loss_atr_multiplier), 2
                )

        # Calculate target
        if targets.target_percent:
            result["target_price"] = round(
                entry_price * (1 + targets.target_percent / 100), 2
            )
        elif targets.target_rr_ratio and result["stop_loss"]:
            risk = entry_price - result["stop_loss"]
            result["target_price"] = round(
                entry_price + (risk * targets.target_rr_ratio), 2
            )

        return result

    def calculate_confidence(
        self,
        confidence_config: Optional[RuleConfidence],
        market_data: Dict[str, Any],
    ) -> float:
        """Calculate confidence score for a triggered rule."""
        if confidence_config is None:
            return 0.7  # Default confidence

        score = confidence_config.base_score

        if confidence_config.modifiers:
            for modifier in confidence_config.modifiers:
                if self._evaluate_modifier_condition(modifier.condition, market_data):
                    score += modifier.adjustment

        # Clamp to valid range
        return max(0.0, min(1.0, score))

    def _evaluate_modifier_condition(
        self, condition_str: str, market_data: Dict[str, Any]
    ) -> bool:
        """Evaluate a simple condition string like 'volume_ratio > 3.0'."""
        try:
            parts = condition_str.split()
            if len(parts) != 3:
                return False

            field_name, op_str, value_str = parts
            field_value = market_data.get(field_name)

            if field_value is None:
                return False

            compare_value = float(value_str)

            # Map operator string to function
            op_map = {
                ">": operator.gt,
                ">=": operator.ge,
                "<": operator.lt,
                "<=": operator.le,
                "==": operator.eq,
                "!=": operator.ne,
            }

            op_func = op_map.get(op_str)
            if op_func is None:
                return False

            return op_func(float(field_value), compare_value)
        except (ValueError, TypeError):
            return False

    def evaluate_rule(
        self, rule: RuleDefinition, market_data: Dict[str, Any]
    ) -> RuleEvaluationResult:
        """Evaluate a single rule against market data."""
        result = RuleEvaluationResult(triggered=False, rule_name=rule.name)

        # Check if rule is enabled
        if not rule.enabled:
            return result

        # Check filters first
        if not self.check_filters(rule.filters, market_data):
            return result

        # Evaluate all conditions (AND logic)
        matched = []
        for condition in rule.conditions:
            if self.evaluate_condition(condition, market_data):
                matched.append(f"{condition.field} {condition.operator.value} {condition.value}")
            else:
                # All conditions must match
                return result

        # All conditions matched
        result.triggered = True
        result.matched_conditions = matched

        # Get entry price
        entry_price = market_data.get("price", 0)
        result.entry_price = entry_price

        # Calculate targets
        targets = self.calculate_targets(entry_price, rule.targets, market_data)
        result.stop_loss = targets["stop_loss"]
        result.target_price = targets["target_price"]

        # Calculate confidence
        result.confidence = self.calculate_confidence(rule.confidence, market_data)

        return result

    def evaluate_all_rules(
        self, market_data: Dict[str, Any]
    ) -> List[RuleEvaluationResult]:
        """Evaluate all active rules against market data."""
        results = []

        for rule in self.get_active_rules():
            result = self.evaluate_rule(rule, market_data)
            if result.triggered:
                results.append(result)

        return results
