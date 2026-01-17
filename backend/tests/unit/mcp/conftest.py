"""Pytest fixtures for MCP tools testing.

These fixtures provide isolated database sessions for testing MCP tools
without affecting the main application database.
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
async def mcp_test_engine():
    """Create a test database engine for MCP tests."""
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
async def mcp_session_factory(mcp_test_engine):
    """Create a session factory for MCP tests."""
    session_factory = async_sessionmaker(
        mcp_test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return session_factory


@pytest_asyncio.fixture(scope="function")
async def mcp_db_session(mcp_session_factory) -> AsyncIterator[AsyncSession]:
    """Create a database session for MCP tests."""
    async with mcp_session_factory() as session:
        yield session


@pytest.fixture
def mock_get_db_session(mcp_session_factory):
    """Mock the get_db_session function used by MCP tools."""
    @asynccontextmanager
    async def _mock_get_db_session() -> AsyncIterator[AsyncSession]:
        async with mcp_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return _mock_get_db_session


# ============== Sample Data Fixtures ==============


@pytest_asyncio.fixture
async def mcp_sample_rule(mcp_db_session: AsyncSession) -> Rule:
    """Create a sample rule for MCP testing."""
    rule = Rule(
        name="MCP Test Rule",
        description="A rule for testing MCP tools",
        rule_type="price",
        config_yaml="""
conditions:
  - field: price_change_percent
    operator: ">="
    value: 5.0
  - field: volume_ratio
    operator: ">="
    value: 2.0
targets:
  stop_loss_percent: -3.0
  target_percent: 6.0
confidence:
  base_score: 0.75
""",
        is_active=True,
        priority=10,
    )
    mcp_db_session.add(rule)
    await mcp_db_session.commit()
    await mcp_db_session.refresh(rule)
    return rule


@pytest_asyncio.fixture
async def mcp_inactive_rule(mcp_db_session: AsyncSession) -> Rule:
    """Create an inactive rule for MCP testing."""
    rule = Rule(
        name="Inactive MCP Rule",
        description="A disabled rule for testing",
        rule_type="volume",
        config_yaml="conditions: []",
        is_active=False,
        priority=5,
    )
    mcp_db_session.add(rule)
    await mcp_db_session.commit()
    await mcp_db_session.refresh(rule)
    return rule


@pytest_asyncio.fixture
async def mcp_sample_alert(mcp_db_session: AsyncSession, mcp_sample_rule: Rule) -> Alert:
    """Create a sample alert for MCP testing."""
    alert = Alert(
        rule_id=mcp_sample_rule.id,
        symbol="AAPL",
        timestamp=datetime.utcnow(),
        setup_type="breakout",
        entry_price=150.50,
        stop_loss=145.00,
        target_price=165.00,
        confidence_score=0.85,
        market_data_json={
            "price": 150.50,
            "volume": 5000000,
            "volume_ratio": 2.5,
            "day_high": 152.00,
            "day_low": 148.00,
        },
        is_read=False,
    )
    mcp_db_session.add(alert)
    await mcp_db_session.commit()
    await mcp_db_session.refresh(alert)
    return alert


@pytest_asyncio.fixture
async def mcp_multiple_alerts(mcp_db_session: AsyncSession, mcp_sample_rule: Rule) -> list[Alert]:
    """Create multiple alerts for comprehensive MCP testing."""
    alerts = []
    now = datetime.utcnow()

    test_data = [
        ("AAPL", "breakout", 150.0, 0.90, False, now - timedelta(hours=1)),
        ("GOOGL", "volume_spike", 2800.0, 0.75, True, now - timedelta(hours=2)),
        ("MSFT", "momentum", 380.0, 0.80, False, now - timedelta(hours=3)),
        ("TSLA", "gap_up", 250.0, 0.70, True, now - timedelta(days=1)),
        ("NVDA", "breakout", 450.0, 0.95, False, now - timedelta(days=2)),
        ("META", "gap_down", 320.0, 0.65, True, now - timedelta(days=3)),
        ("AMZN", "volume_spike", 175.0, 0.85, False, now - timedelta(days=5)),
    ]

    for symbol, setup_type, price, confidence, is_read, timestamp in test_data:
        alert = Alert(
            rule_id=mcp_sample_rule.id,
            symbol=symbol,
            timestamp=timestamp,
            setup_type=setup_type,
            entry_price=price,
            stop_loss=price * 0.97,
            target_price=price * 1.06,
            confidence_score=confidence,
            market_data_json={"price": price, "volume": 1000000},
            is_read=is_read,
        )
        mcp_db_session.add(alert)
        alerts.append(alert)

    await mcp_db_session.commit()
    for alert in alerts:
        await mcp_db_session.refresh(alert)

    return alerts


@pytest_asyncio.fixture
async def mcp_watchlist_items(mcp_db_session: AsyncSession) -> list[Watchlist]:
    """Create multiple watchlist items for MCP testing."""
    items = []

    test_data = [
        ("AAPL", "Tech giant, watching for earnings", True),
        ("GOOGL", "AI momentum play", True),
        ("MSFT", "Cloud growth story", True),
        ("TSLA", "Volatile, high beta", False),
    ]

    for symbol, notes, is_active in test_data:
        item = Watchlist(
            symbol=symbol,
            notes=notes,
            is_active=is_active,
        )
        mcp_db_session.add(item)
        items.append(item)

    await mcp_db_session.commit()
    for item in items:
        await mcp_db_session.refresh(item)

    return items
