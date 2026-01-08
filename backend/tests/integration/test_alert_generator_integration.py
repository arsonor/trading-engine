"""Integration tests for AlertGenerator service."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alert, Rule
from app.schemas.market_data import MarketData
from app.services.alert_generator import AlertGenerator, get_alert_generator
from tests.conftest import TestSessionLocal


@pytest_asyncio.fixture
async def simple_price_rule(db_session: AsyncSession) -> Rule:
    """Create a simple price threshold rule for testing."""
    rule = Rule(
        name="Simple Price Alert",
        description="Alert when price > 100",
        rule_type="price",
        config_yaml="""
conditions:
  - field: price
    operator: ">"
    value: 100
""",
        is_active=True,
        priority=10,
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)
    return rule


@pytest_asyncio.fixture
async def volume_rule(db_session: AsyncSession) -> Rule:
    """Create a volume threshold rule for testing."""
    rule = Rule(
        name="Volume Spike Alert",
        description="Alert when volume > 500000",
        rule_type="volume",
        config_yaml="""
conditions:
  - field: volume
    operator: ">"
    value: 500000
""",
        is_active=True,
        priority=5,
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)
    return rule


@pytest_asyncio.fixture
async def inactive_rule(db_session: AsyncSession) -> Rule:
    """Create an inactive rule that should not trigger."""
    rule = Rule(
        name="Inactive Rule",
        description="This should not trigger",
        rule_type="price",
        config_yaml="""
conditions:
  - field: price
    operator: ">"
    value: 0
""",
        is_active=False,
        priority=1,
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)
    return rule


class TestAlertGeneratorIntegration:
    """Integration tests for AlertGenerator with database."""

    @pytest.mark.asyncio
    async def test_market_data_triggers_alert_creation(
        self, db_session: AsyncSession, simple_price_rule: Rule
    ):
        """Test: Market data above threshold creates alert in database."""
        AlertGenerator.reset_instance()
        generator = AlertGenerator.get_instance()

        # Patch async_session_maker for the entire test
        with patch('app.services.alert_generator.async_session_maker', TestSessionLocal):
            await generator.start()

            # Market data that should trigger the rule (price > 100)
            market_data = MarketData(
                symbol="AAPL",
                price=150.0,
                volume=1000000,
                timestamp=datetime.utcnow(),
            )

            # Mock WebSocket broadcast
            with patch('app.services.alert_generator.get_manager') as mock_get_manager:
                mock_manager = MagicMock()
                mock_manager.broadcast_to_channel = AsyncMock()
                mock_get_manager.return_value = mock_manager

                # Process market data
                await generator.on_market_data("AAPL", market_data)

            await generator.stop()

        # Check alert was created in database
        result = await db_session.execute(select(Alert))
        alerts = result.scalars().all()

        assert len(alerts) == 1
        assert alerts[0].symbol == "AAPL"
        assert alerts[0].entry_price == 150.0
        assert alerts[0].rule_id == simple_price_rule.id

    @pytest.mark.asyncio
    async def test_market_data_below_threshold_no_alert(
        self, db_session: AsyncSession, simple_price_rule: Rule
    ):
        """Test: Market data below threshold does not create alert."""
        AlertGenerator.reset_instance()
        generator = AlertGenerator.get_instance()

        with patch('app.services.alert_generator.async_session_maker', TestSessionLocal):
            await generator.start()

            # Market data that should NOT trigger the rule (price <= 100)
            market_data = MarketData(
                symbol="AAPL",
                price=50.0,
                volume=1000000,
                timestamp=datetime.utcnow(),
            )

            # Process market data
            await generator.on_market_data("AAPL", market_data)

            await generator.stop()

        # Check no alert was created
        result = await db_session.execute(select(Alert))
        alerts = result.scalars().all()

        assert len(alerts) == 0

    @pytest.mark.asyncio
    async def test_multiple_rules_trigger_multiple_alerts(
        self,
        db_session: AsyncSession,
        simple_price_rule: Rule,
        volume_rule: Rule,
    ):
        """Test: Market data matching multiple rules creates multiple alerts."""
        AlertGenerator.reset_instance()
        generator = AlertGenerator.get_instance()

        with patch('app.services.alert_generator.async_session_maker', TestSessionLocal):
            await generator.start()

            # Market data that triggers both rules
            market_data = MarketData(
                symbol="TSLA",
                price=200.0,  # > 100
                volume=1000000,  # > 500000
                timestamp=datetime.utcnow(),
            )

            # Mock WebSocket broadcast
            with patch('app.services.alert_generator.get_manager') as mock_get_manager:
                mock_manager = MagicMock()
                mock_manager.broadcast_to_channel = AsyncMock()
                mock_get_manager.return_value = mock_manager

                # Process market data
                await generator.on_market_data("TSLA", market_data)

            await generator.stop()

        # Check alerts were created
        result = await db_session.execute(select(Alert))
        alerts = result.scalars().all()

        assert len(alerts) == 2
        rule_ids = {alert.rule_id for alert in alerts}
        assert simple_price_rule.id in rule_ids
        assert volume_rule.id in rule_ids

    @pytest.mark.asyncio
    async def test_inactive_rule_does_not_trigger(
        self,
        db_session: AsyncSession,
        inactive_rule: Rule,
    ):
        """Test: Inactive rules do not generate alerts."""
        AlertGenerator.reset_instance()
        generator = AlertGenerator.get_instance()

        with patch('app.services.alert_generator.async_session_maker', TestSessionLocal):
            await generator.start()

            # Market data that would trigger the rule if active
            market_data = MarketData(
                symbol="AAPL",
                price=150.0,
                timestamp=datetime.utcnow(),
            )

            # Process market data
            await generator.on_market_data("AAPL", market_data)

            await generator.stop()

        # Check no alert was created
        result = await db_session.execute(select(Alert))
        alerts = result.scalars().all()

        assert len(alerts) == 0

    @pytest.mark.asyncio
    async def test_alert_has_correct_fields(
        self, db_session: AsyncSession
    ):
        """Test: Created alert has all correct fields populated."""
        # Create a rule with targets
        rule = Rule(
            name="Full Rule",
            description="Rule with targets",
            rule_type="breakout",
            config_yaml="""
conditions:
  - field: price
    operator: ">"
    value: 100
targets:
  stop_loss_percent: -3.0
  target_percent: 6.0
confidence:
  base_score: 0.8
""",
            is_active=True,
            priority=10,
        )
        db_session.add(rule)
        await db_session.commit()
        await db_session.refresh(rule)

        AlertGenerator.reset_instance()
        generator = AlertGenerator.get_instance()

        with patch('app.services.alert_generator.async_session_maker', TestSessionLocal):
            await generator.start()

            market_data = MarketData(
                symbol="GOOGL",
                price=150.0,
                volume=500000,
                timestamp=datetime.utcnow(),
            )

            # Mock WebSocket broadcast
            with patch('app.services.alert_generator.get_manager') as mock_get_manager:
                mock_manager = MagicMock()
                mock_manager.broadcast_to_channel = AsyncMock()
                mock_get_manager.return_value = mock_manager

                await generator.on_market_data("GOOGL", market_data)

            await generator.stop()

        # Check alert fields
        result = await db_session.execute(select(Alert))
        alerts = result.scalars().all()

        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.symbol == "GOOGL"
        assert alert.entry_price == 150.0
        assert alert.stop_loss is not None  # Should be calculated
        assert alert.target_price is not None  # Should be calculated
        assert alert.confidence_score == 0.8
        assert alert.rule_id == rule.id
        assert alert.is_read is False
        assert alert.market_data_json is not None

    @pytest.mark.asyncio
    async def test_websocket_broadcast_called(
        self, db_session: AsyncSession, simple_price_rule: Rule
    ):
        """Test: WebSocket broadcast is called when alert is created."""
        AlertGenerator.reset_instance()
        generator = AlertGenerator.get_instance()

        with patch('app.services.alert_generator.async_session_maker', TestSessionLocal):
            await generator.start()

            market_data = MarketData(
                symbol="NVDA",
                price=200.0,
                timestamp=datetime.utcnow(),
            )

            # Mock WebSocket manager
            with patch('app.services.alert_generator.get_manager') as mock_get_manager:
                mock_manager = MagicMock()
                mock_manager.broadcast_to_channel = AsyncMock()
                mock_get_manager.return_value = mock_manager

                await generator.on_market_data("NVDA", market_data)

                # Check broadcast was called
                mock_manager.broadcast_to_channel.assert_called_once()
                call_args = mock_manager.broadcast_to_channel.call_args
                assert call_args[0][0] == "alerts"
                assert call_args[0][1]["type"] == "alert"
                assert call_args[0][1]["data"]["symbol"] == "NVDA"

            await generator.stop()

    @pytest.mark.asyncio
    async def test_cache_refresh_loads_rules(
        self, db_session: AsyncSession, simple_price_rule: Rule
    ):
        """Test: Rules are loaded into cache on refresh."""
        AlertGenerator.reset_instance()
        generator = AlertGenerator.get_instance()

        with patch('app.services.alert_generator.async_session_maker', TestSessionLocal):
            await generator.refresh_rules_cache(force=True)

        # Check rule is in cache
        assert len(generator._rules_cache) == 1
        assert simple_price_rule.id in generator._rules_cache

        await generator.stop()

    @pytest.mark.asyncio
    async def test_rule_toggle_affects_alerts(
        self, db_session: AsyncSession, simple_price_rule: Rule
    ):
        """Test: Toggling rule affects alert generation after cache refresh."""
        AlertGenerator.reset_instance()
        generator = AlertGenerator.get_instance()

        with patch('app.services.alert_generator.async_session_maker', TestSessionLocal):
            await generator.start()

            market_data = MarketData(
                symbol="AAPL",
                price=150.0,
                timestamp=datetime.utcnow(),
            )

            # First, rule is active - should trigger
            with patch('app.services.alert_generator.get_manager') as mock_get_manager:
                mock_manager = MagicMock()
                mock_manager.broadcast_to_channel = AsyncMock()
                mock_get_manager.return_value = mock_manager

                await generator.on_market_data("AAPL", market_data)

            result = await db_session.execute(select(Alert))
            alerts_before = result.scalars().all()
            assert len(alerts_before) == 1

            # Deactivate rule
            simple_price_rule.is_active = False
            await db_session.commit()

            # Force cache refresh
            await generator.refresh_rules_cache(force=True)

            # Try to trigger again - should not create new alert
            await generator.on_market_data("AAPL", market_data)

            await generator.stop()

        result = await db_session.execute(select(Alert))
        alerts_after = result.scalars().all()
        assert len(alerts_after) == 1  # No new alert created


class TestAlertGeneratorRuleEngine:
    """Integration tests for RuleEngine within AlertGenerator."""

    @pytest.mark.asyncio
    async def test_reference_value_comparison(self, db_session: AsyncSession):
        """Test rule with reference value comparison."""
        # Create rule that compares price to a reference field
        rule = Rule(
            name="Reference Rule",
            description="Price above day high",
            rule_type="price",
            config_yaml="""
conditions:
  - field: price
    operator: ">"
    value: day_high
""",
            is_active=True,
            priority=10,
        )
        db_session.add(rule)
        await db_session.commit()

        AlertGenerator.reset_instance()
        generator = AlertGenerator.get_instance()

        with patch('app.services.alert_generator.async_session_maker', TestSessionLocal):
            await generator.start()

            # Market data where price > day_high
            market_data = MarketData(
                symbol="AAPL",
                price=155.0,
                day_high=150.0,
                timestamp=datetime.utcnow(),
            )

            with patch('app.services.alert_generator.get_manager') as mock_get_manager:
                mock_manager = MagicMock()
                mock_manager.broadcast_to_channel = AsyncMock()
                mock_get_manager.return_value = mock_manager

                await generator.on_market_data("AAPL", market_data)

            await generator.stop()

        result = await db_session.execute(select(Alert))
        alerts = result.scalars().all()

        assert len(alerts) == 1
        assert alerts[0].symbol == "AAPL"

    @pytest.mark.asyncio
    async def test_filter_blocks_low_volume(self, db_session: AsyncSession):
        """Test rule filters block low volume stocks."""
        rule = Rule(
            name="Filtered Rule",
            description="Price above 100 with min volume",
            rule_type="price",
            config_yaml="""
conditions:
  - field: price
    operator: ">"
    value: 100
filters:
  min_volume: 500000
""",
            is_active=True,
            priority=10,
        )
        db_session.add(rule)
        await db_session.commit()

        AlertGenerator.reset_instance()
        generator = AlertGenerator.get_instance()

        with patch('app.services.alert_generator.async_session_maker', TestSessionLocal):
            await generator.start()

            # Market data with low volume (below filter)
            market_data = MarketData(
                symbol="AAPL",
                price=150.0,
                volume=100000,  # Below min_volume filter
                timestamp=datetime.utcnow(),
            )

            await generator.on_market_data("AAPL", market_data)

            await generator.stop()

        result = await db_session.execute(select(Alert))
        alerts = result.scalars().all()

        # Should not trigger due to filter
        assert len(alerts) == 0
