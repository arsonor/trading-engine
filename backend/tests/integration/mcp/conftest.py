"""Pytest fixtures for MCP integration testing.

These fixtures provide a complete test environment with database isolation
for testing MCP tools in realistic scenarios.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import AsyncIterator
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.alert import Alert
from app.models.rule import Rule
from app.models.watchlist import Watchlist

# Test database URL (in-memory SQLite)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def integration_engine():
    """Create a test database engine for integration tests."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        future=True,
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Cleanup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def integration_session_factory(integration_engine):
    """Create a session factory for integration tests."""
    session_factory = async_sessionmaker(
        integration_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return session_factory


@pytest_asyncio.fixture(scope="function")
async def integration_db_session(integration_session_factory) -> AsyncIterator[AsyncSession]:
    """Create a database session for integration tests."""
    async with integration_session_factory() as session:
        yield session


@pytest.fixture
def mock_mcp_db_session(integration_session_factory):
    """Mock the get_db_session function for all MCP modules."""
    @asynccontextmanager
    async def _mock_get_db_session() -> AsyncIterator[AsyncSession]:
        async with integration_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return _mock_get_db_session


@pytest.fixture
def patch_all_mcp_modules(mock_mcp_db_session):
    """Context manager to patch get_db_session in all MCP modules."""
    patches = [
        patch("app.mcp.tools.alerts.get_db_session", mock_mcp_db_session),
        patch("app.mcp.tools.rules.get_db_session", mock_mcp_db_session),
        patch("app.mcp.tools.analysis.get_db_session", mock_mcp_db_session),
        patch("app.mcp.tools.watchlist.get_db_session", mock_mcp_db_session),
        patch("app.mcp.resources.data.get_db_session", mock_mcp_db_session),
    ]

    for p in patches:
        p.start()

    yield

    for p in patches:
        p.stop()


# ============== Realistic Test Data Fixtures ==============


@pytest_asyncio.fixture
async def trading_rules(integration_db_session: AsyncSession) -> list[Rule]:
    """Create a realistic set of trading rules."""
    rules = [
        Rule(
            name="High Volume Breakout",
            description="Triggers on high volume price breakouts above resistance",
            rule_type="price",
            config_yaml="""
conditions:
  - field: price_change_percent
    operator: ">="
    value: 3.0
  - field: volume_ratio
    operator: ">="
    value: 2.5
targets:
  stop_loss_percent: -3.0
  target_percent: 9.0
confidence:
  base_score: 0.80
""",
            is_active=True,
            priority=20,
        ),
        Rule(
            name="Gap Up Scanner",
            description="Detects stocks gapping up in pre-market",
            rule_type="gap",
            config_yaml="""
conditions:
  - field: gap_percent
    operator: ">="
    value: 5.0
  - field: pre_market_volume
    operator: ">="
    value: 100000
targets:
  stop_loss_percent: -4.0
  target_percent: 8.0
confidence:
  base_score: 0.75
""",
            is_active=True,
            priority=15,
        ),
        Rule(
            name="Volume Spike Alert",
            description="Unusual volume detection",
            rule_type="volume",
            config_yaml="""
conditions:
  - field: volume_ratio
    operator: ">="
    value: 3.0
targets:
  stop_loss_percent: -2.5
  target_percent: 5.0
confidence:
  base_score: 0.70
""",
            is_active=True,
            priority=10,
        ),
        Rule(
            name="Disabled Test Rule",
            description="This rule is disabled for testing",
            rule_type="technical",
            config_yaml="conditions: []",
            is_active=False,
            priority=5,
        ),
    ]

    for rule in rules:
        integration_db_session.add(rule)

    await integration_db_session.commit()
    for rule in rules:
        await integration_db_session.refresh(rule)

    return rules


@pytest_asyncio.fixture
async def trading_alerts(
    integration_db_session: AsyncSession,
    trading_rules: list[Rule]
) -> list[Alert]:
    """Create a realistic set of trading alerts."""
    now = datetime.utcnow()
    active_rules = [r for r in trading_rules if r.is_active]

    alerts_data = [
        # Recent high-confidence alerts
        ("NVDA", "breakout", 875.50, 0.92, False, now - timedelta(hours=1), active_rules[0].id),
        ("AMD", "breakout", 165.25, 0.88, False, now - timedelta(hours=2), active_rules[0].id),
        ("SMCI", "volume_spike", 925.00, 0.85, False, now - timedelta(hours=3), active_rules[2].id),

        # Today's alerts
        ("AAPL", "gap_up", 182.50, 0.78, True, now - timedelta(hours=5), active_rules[1].id),
        ("MSFT", "momentum", 415.00, 0.75, True, now - timedelta(hours=6), active_rules[0].id),

        # Yesterday's alerts
        ("GOOGL", "breakout", 155.75, 0.82, True, now - timedelta(days=1, hours=2), active_rules[0].id),
        ("META", "volume_spike", 505.00, 0.70, True, now - timedelta(days=1, hours=5), active_rules[2].id),

        # Older alerts
        ("TSLA", "gap_down", 175.00, 0.65, True, now - timedelta(days=3), active_rules[1].id),
        ("AMZN", "breakout", 185.50, 0.80, True, now - timedelta(days=5), active_rules[0].id),
        ("NFLX", "momentum", 625.00, 0.72, True, now - timedelta(days=7), active_rules[0].id),
    ]

    alerts = []
    for symbol, setup_type, price, confidence, is_read, timestamp, rule_id in alerts_data:
        alert = Alert(
            rule_id=rule_id,
            symbol=symbol,
            timestamp=timestamp,
            setup_type=setup_type,
            entry_price=price,
            stop_loss=price * 0.97,
            target_price=price * 1.06,
            confidence_score=confidence,
            market_data_json={
                "price": price,
                "volume": 2500000,
                "volume_ratio": 2.8,
                "day_high": price * 1.02,
                "day_low": price * 0.98,
            },
            is_read=is_read,
        )
        integration_db_session.add(alert)
        alerts.append(alert)

    await integration_db_session.commit()
    for alert in alerts:
        await integration_db_session.refresh(alert)

    return alerts


@pytest_asyncio.fixture
async def watchlist(integration_db_session: AsyncSession) -> list[Watchlist]:
    """Create a realistic watchlist."""
    items = [
        Watchlist(symbol="NVDA", notes="AI chip leader, watching for earnings", is_active=True),
        Watchlist(symbol="AMD", notes="Competitor to NVDA, momentum play", is_active=True),
        Watchlist(symbol="AAPL", notes="Core tech holding", is_active=True),
        Watchlist(symbol="MSFT", notes="Cloud and AI growth", is_active=True),
        Watchlist(symbol="GOOGL", notes="AI and search dominance", is_active=True),
        Watchlist(symbol="TSLA", notes="High volatility, trade carefully", is_active=False),
    ]

    for item in items:
        integration_db_session.add(item)

    await integration_db_session.commit()
    for item in items:
        await integration_db_session.refresh(item)

    return items
