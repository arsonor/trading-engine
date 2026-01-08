"""Unit tests for AlertGenerator service."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.rule_engine import (
    OperatorType,
    RuleCondition,
    RuleConfidence,
    RuleDefinition,
    RuleEvaluationResult,
    RuleFilters,
    RuleTargets,
)
from app.models import Alert, Rule
from app.schemas.market_data import MarketData
from app.services.alert_generator import AlertGenerator, get_alert_generator


class TestAlertGeneratorSingleton:
    """Tests for singleton pattern."""

    def setup_method(self):
        """Reset singleton before each test."""
        AlertGenerator.reset_instance()

    def test_singleton_pattern(self):
        """Test AlertGenerator uses singleton pattern."""
        instance1 = AlertGenerator.get_instance()
        instance2 = AlertGenerator.get_instance()
        assert instance1 is instance2

    def test_get_alert_generator_returns_singleton(self):
        """Test get_alert_generator returns same instance."""
        instance1 = get_alert_generator()
        instance2 = get_alert_generator()
        assert instance1 is instance2

    def test_reset_instance_creates_new_instance(self):
        """Test reset_instance creates fresh instance."""
        instance1 = AlertGenerator.get_instance()
        AlertGenerator.reset_instance()
        instance2 = AlertGenerator.get_instance()
        assert instance1 is not instance2


class TestAlertGeneratorLifecycle:
    """Tests for start/stop lifecycle."""

    def setup_method(self):
        """Reset singleton before each test."""
        AlertGenerator.reset_instance()

    @pytest.mark.asyncio
    async def test_start_sets_running_flag(self):
        """Test start() sets running flag."""
        generator = AlertGenerator.get_instance()

        with patch.object(generator, 'refresh_rules_cache', new_callable=AsyncMock):
            await generator.start()

        assert generator._running is True

    @pytest.mark.asyncio
    async def test_start_loads_rules_cache(self):
        """Test start() loads rules cache."""
        generator = AlertGenerator.get_instance()

        with patch.object(generator, 'refresh_rules_cache', new_callable=AsyncMock) as mock_refresh:
            await generator.start()
            mock_refresh.assert_called_once_with(force=True)

    @pytest.mark.asyncio
    async def test_stop_clears_state(self):
        """Test stop() clears running flag and cache."""
        generator = AlertGenerator.get_instance()
        generator._running = True
        generator._rules_cache = {1: ("rule", "def")}
        generator._last_cache_refresh = datetime.utcnow()

        await generator.stop()

        assert generator._running is False
        assert generator._rules_cache == {}
        assert generator._last_cache_refresh is None

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self):
        """Test calling start() multiple times is safe."""
        generator = AlertGenerator.get_instance()

        with patch.object(generator, 'refresh_rules_cache', new_callable=AsyncMock) as mock_refresh:
            await generator.start()
            await generator.start()  # Second call should be no-op

            # Should only be called once
            mock_refresh.assert_called_once()


class TestMarketDataEnrichment:
    """Tests for _enrich_market_data method."""

    def setup_method(self):
        """Reset singleton before each test."""
        AlertGenerator.reset_instance()
        self.generator = AlertGenerator.get_instance()

    def test_enrich_preserves_basic_fields(self):
        """Test basic fields are preserved in enriched data."""
        market_data = MarketData(
            symbol="AAPL",
            price=150.0,
            volume=1000000,
            timestamp=datetime.utcnow(),
        )

        result = self.generator._enrich_market_data("AAPL", market_data)

        assert result["symbol"] == "AAPL"
        assert result["price"] == 150.0
        assert result["volume"] == 1000000

    def test_enrich_calculates_price_change_percent(self):
        """Test price_change_percent is calculated when prev_close available."""
        market_data = MarketData(
            symbol="AAPL",
            price=110.0,
            prev_close=100.0,
            timestamp=datetime.utcnow(),
        )

        result = self.generator._enrich_market_data("AAPL", market_data)

        assert result["price_change_percent"] == 10.0  # (110-100)/100 * 100

    def test_enrich_calculates_gap_percent(self):
        """Test gap_percent is calculated when day_open and prev_close available."""
        market_data = MarketData(
            symbol="AAPL",
            price=105.0,
            day_open=105.0,
            prev_close=100.0,
            timestamp=datetime.utcnow(),
        )

        result = self.generator._enrich_market_data("AAPL", market_data)

        assert result["gap_percent"] == 5.0  # (105-100)/100 * 100

    def test_enrich_missing_fields_default_to_none(self):
        """Test missing fields default to None for graceful rule handling."""
        market_data = MarketData(
            symbol="AAPL",
            price=150.0,
            timestamp=datetime.utcnow(),
        )

        result = self.generator._enrich_market_data("AAPL", market_data)

        assert result["volume_ratio"] is None
        assert result["resistance_level"] is None
        assert result["sma_20"] is None
        assert result["pre_market_high"] is None
        assert result["float_shares"] is None
        assert result["short_interest"] is None
        assert result["atr"] is None

    def test_enrich_no_price_change_without_prev_close(self):
        """Test price_change_percent not calculated without prev_close."""
        market_data = MarketData(
            symbol="AAPL",
            price=150.0,
            timestamp=datetime.utcnow(),
        )

        result = self.generator._enrich_market_data("AAPL", market_data)

        assert "price_change_percent" not in result or result.get("price_change_percent") is None


class TestRuleParsing:
    """Tests for _parse_rule_to_definition method."""

    def setup_method(self):
        """Reset singleton before each test."""
        AlertGenerator.reset_instance()
        self.generator = AlertGenerator.get_instance()

    def test_parse_valid_rule_yaml(self):
        """Test parsing valid rule YAML."""
        rule = MagicMock()
        rule.name = "Test Rule"
        rule.description = "Test description"
        rule.rule_type = "price"
        rule.is_active = True
        rule.priority = 10
        rule.config_yaml = """
conditions:
  - field: price
    operator: ">"
    value: 100
"""

        result = self.generator._parse_rule_to_definition(rule)

        assert result is not None
        assert result.name == "Test Rule"
        assert result.description == "Test description"
        assert result.type == "price"
        assert result.enabled is True
        assert result.priority == 10
        assert len(result.conditions) == 1
        assert result.conditions[0].field == "price"
        assert result.conditions[0].operator == OperatorType.GT
        assert result.conditions[0].value == 100

    def test_parse_rule_with_filters(self):
        """Test parsing rule with filters."""
        rule = MagicMock()
        rule.name = "Filtered Rule"
        rule.description = None
        rule.rule_type = "price"
        rule.is_active = True
        rule.priority = 5
        rule.config_yaml = """
conditions:
  - field: price
    operator: ">"
    value: 100
filters:
  min_price: 10.0
  max_price: 500.0
  min_volume: 100000
"""

        result = self.generator._parse_rule_to_definition(rule)

        assert result is not None
        assert result.filters is not None
        assert result.filters.min_price == 10.0
        assert result.filters.max_price == 500.0
        assert result.filters.min_volume == 100000

    def test_parse_rule_with_targets(self):
        """Test parsing rule with targets."""
        rule = MagicMock()
        rule.name = "Target Rule"
        rule.description = None
        rule.rule_type = "price"
        rule.is_active = True
        rule.priority = 5
        rule.config_yaml = """
conditions:
  - field: price
    operator: ">"
    value: 100
targets:
  stop_loss_percent: -3.0
  target_percent: 6.0
"""

        result = self.generator._parse_rule_to_definition(rule)

        assert result is not None
        assert result.targets is not None
        assert result.targets.stop_loss_percent == -3.0
        assert result.targets.target_percent == 6.0

    def test_parse_rule_with_confidence(self):
        """Test parsing rule with confidence settings."""
        rule = MagicMock()
        rule.name = "Confidence Rule"
        rule.description = None
        rule.rule_type = "price"
        rule.is_active = True
        rule.priority = 5
        rule.config_yaml = """
conditions:
  - field: price
    operator: ">"
    value: 100
confidence:
  base_score: 0.75
  modifiers:
    - condition: "volume > 1000000"
      adjustment: 0.1
"""

        result = self.generator._parse_rule_to_definition(rule)

        assert result is not None
        assert result.confidence is not None
        assert result.confidence.base_score == 0.75
        assert len(result.confidence.modifiers) == 1
        assert result.confidence.modifiers[0].condition == "volume > 1000000"
        assert result.confidence.modifiers[0].adjustment == 0.1

    def test_parse_invalid_yaml_returns_none(self):
        """Test invalid YAML returns None gracefully."""
        rule = MagicMock()
        rule.name = "Invalid Rule"
        rule.config_yaml = "{{{{invalid yaml"

        result = self.generator._parse_rule_to_definition(rule)

        assert result is None

    def test_parse_empty_conditions_returns_none(self):
        """Test rule with no conditions returns None."""
        rule = MagicMock()
        rule.name = "Empty Rule"
        rule.config_yaml = """
conditions: []
"""

        result = self.generator._parse_rule_to_definition(rule)

        assert result is None

    def test_parse_missing_conditions_returns_none(self):
        """Test rule with missing conditions returns None."""
        rule = MagicMock()
        rule.name = "No Conditions Rule"
        rule.config_yaml = """
filters:
  min_price: 10
"""

        result = self.generator._parse_rule_to_definition(rule)

        assert result is None


class TestSetupTypeDetermination:
    """Tests for _determine_setup_type method."""

    def setup_method(self):
        """Reset singleton before each test."""
        AlertGenerator.reset_instance()
        self.generator = AlertGenerator.get_instance()

    def test_breakout_in_name(self):
        """Test 'breakout' in name returns breakout."""
        assert self.generator._determine_setup_type("Breakout Setup") == "breakout"
        assert self.generator._determine_setup_type("breakout_rule") == "breakout"

    def test_volume_spike_in_name(self):
        """Test volume-related name returns volume_spike."""
        assert self.generator._determine_setup_type("Volume Alert") == "volume_spike"
        assert self.generator._determine_setup_type("spike_detector") == "volume_spike"

    def test_gap_up_in_name(self):
        """Test 'gap_up' in name returns gap_up."""
        assert self.generator._determine_setup_type("Gap Up Alert") == "gap_up"
        assert self.generator._determine_setup_type("gap_up_scanner") == "gap_up"

    def test_gap_down_in_name(self):
        """Test 'gap_down' in name returns gap_down."""
        assert self.generator._determine_setup_type("Gap Down Alert") == "gap_down"
        assert self.generator._determine_setup_type("gap_down_detector") == "gap_down"

    def test_momentum_in_name(self):
        """Test 'momentum' in name returns momentum."""
        assert self.generator._determine_setup_type("Momentum Play") == "momentum"

    def test_default_returns_breakout(self):
        """Test unknown name defaults to breakout."""
        assert self.generator._determine_setup_type("Random Rule") == "breakout"
        assert self.generator._determine_setup_type("price_threshold") == "breakout"


class TestCacheManagement:
    """Tests for cache-related functionality."""

    def setup_method(self):
        """Reset singleton before each test."""
        AlertGenerator.reset_instance()
        self.generator = AlertGenerator.get_instance()

    @pytest.mark.asyncio
    async def test_invalidate_cache_clears_timestamp(self):
        """Test invalidate_cache clears last refresh timestamp."""
        self.generator._last_cache_refresh = datetime.utcnow()

        await self.generator.invalidate_cache()

        assert self.generator._last_cache_refresh is None

    @pytest.mark.asyncio
    async def test_cache_ttl_prevents_refresh(self):
        """Test cache TTL prevents frequent database queries."""
        self.generator._last_cache_refresh = datetime.utcnow()
        self.generator._cache_ttl = 60

        with patch('app.services.alert_generator.async_session_maker') as mock_session:
            await self.generator.refresh_rules_cache(force=False)

            # Session should not be created due to TTL
            mock_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_force_refresh_bypasses_ttl(self):
        """Test force=True bypasses TTL check."""
        self.generator._last_cache_refresh = datetime.utcnow()

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch('app.services.alert_generator.async_session_maker', return_value=mock_session):
            await self.generator.refresh_rules_cache(force=True)

            # Session should be created despite recent refresh
            mock_session.execute.assert_called_once()


class TestOnMarketData:
    """Tests for on_market_data callback."""

    def setup_method(self):
        """Reset singleton before each test."""
        AlertGenerator.reset_instance()
        self.generator = AlertGenerator.get_instance()

    @pytest.mark.asyncio
    async def test_on_market_data_when_not_running(self):
        """Test on_market_data does nothing when service not running."""
        self.generator._running = False

        market_data = MarketData(
            symbol="AAPL",
            price=150.0,
            timestamp=datetime.utcnow(),
        )

        with patch.object(self.generator, 'refresh_rules_cache', new_callable=AsyncMock) as mock_refresh:
            await self.generator.on_market_data("AAPL", market_data)

            # Should not refresh cache when not running
            mock_refresh.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_market_data_refreshes_cache(self):
        """Test on_market_data refreshes cache when running."""
        self.generator._running = True

        market_data = MarketData(
            symbol="AAPL",
            price=150.0,
            timestamp=datetime.utcnow(),
        )

        with patch.object(self.generator, 'refresh_rules_cache', new_callable=AsyncMock) as mock_refresh:
            with patch.object(self.generator, '_evaluate_and_generate', new_callable=AsyncMock):
                await self.generator.on_market_data("AAPL", market_data)

                mock_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_market_data_handles_errors_gracefully(self):
        """Test on_market_data handles errors without crashing."""
        self.generator._running = True

        market_data = MarketData(
            symbol="AAPL",
            price=150.0,
            timestamp=datetime.utcnow(),
        )

        with patch.object(self.generator, 'refresh_rules_cache', new_callable=AsyncMock) as mock_refresh:
            mock_refresh.side_effect = Exception("Database error")

            # Should not raise exception
            await self.generator.on_market_data("AAPL", market_data)


class TestBroadcastAlert:
    """Tests for _broadcast_alert method."""

    def setup_method(self):
        """Reset singleton before each test."""
        AlertGenerator.reset_instance()
        self.generator = AlertGenerator.get_instance()

    @pytest.mark.asyncio
    async def test_broadcast_calls_websocket_manager(self):
        """Test _broadcast_alert calls WebSocket manager."""
        alert = MagicMock()
        alert.id = 1
        alert.symbol = "AAPL"
        alert.setup_type = "breakout"
        alert.entry_price = 150.0
        alert.stop_loss = 145.0
        alert.target_price = 160.0
        alert.confidence_score = 0.85
        alert.timestamp = datetime.utcnow()
        alert.is_read = False

        mock_manager = MagicMock()
        mock_manager.broadcast_to_channel = AsyncMock()

        with patch('app.services.alert_generator.get_manager', return_value=mock_manager):
            await self.generator._broadcast_alert(alert, "Test Rule")

            mock_manager.broadcast_to_channel.assert_called_once()
            call_args = mock_manager.broadcast_to_channel.call_args
            assert call_args[0][0] == "alerts"
            assert call_args[0][1]["type"] == "alert"
            assert call_args[0][1]["data"]["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_broadcast_handles_errors(self):
        """Test _broadcast_alert handles errors gracefully."""
        alert = MagicMock()
        alert.id = 1
        alert.symbol = "AAPL"
        alert.setup_type = "breakout"
        alert.entry_price = 150.0
        alert.stop_loss = 145.0
        alert.target_price = 160.0
        alert.confidence_score = 0.85
        alert.timestamp = datetime.utcnow()
        alert.is_read = False

        mock_manager = MagicMock()
        mock_manager.broadcast_to_channel = AsyncMock(side_effect=Exception("WebSocket error"))

        with patch('app.services.alert_generator.get_manager', return_value=mock_manager):
            # Should not raise exception
            await self.generator._broadcast_alert(alert, "Test Rule")
