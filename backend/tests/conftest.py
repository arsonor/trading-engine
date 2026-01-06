"""Pytest configuration and fixtures for testing."""

import asyncio
from datetime import datetime
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.main import app
from app.models import Alert, Rule, Watchlist


# Test database URL (in-memory SQLite)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# Create test engine
test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    future=True,
)

# Create test session factory
TestSessionLocal = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a fresh database session for each test."""
    # Create all tables
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSessionLocal() as session:
        yield session

    # Drop all tables after test
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create test client with database override."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ============== Sample Data Fixtures ==============


@pytest_asyncio.fixture
async def sample_rule(db_session: AsyncSession) -> Rule:
    """Create a sample rule for testing."""
    rule = Rule(
        name="Test Breakout Rule",
        description="Test rule for breakout detection",
        rule_type="price",  # Valid RuleType enum value
        config_yaml="""
conditions:
  - field: price
    operator: ">"
    value: resistance_level
  - field: volume_ratio
    operator: ">="
    value: 1.5
filters:
  min_price: 5.0
  max_price: 500.0
targets:
  stop_loss_percent: -3.0
  target_rr_ratio: 2.0
confidence:
  base_score: 0.7
""",
        is_active=True,
        priority=10,
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)
    return rule


@pytest_asyncio.fixture
async def sample_rule_inactive(db_session: AsyncSession) -> Rule:
    """Create an inactive sample rule."""
    rule = Rule(
        name="Inactive Rule",
        description="This rule is disabled",
        rule_type="volume",  # Valid RuleType enum value
        config_yaml="conditions: []",
        is_active=False,
        priority=5,
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)
    return rule


@pytest_asyncio.fixture
async def sample_alert(db_session: AsyncSession, sample_rule: Rule) -> Alert:
    """Create a sample alert for testing."""
    alert = Alert(
        rule_id=sample_rule.id,
        symbol="AAPL",
        timestamp=datetime.utcnow(),
        setup_type="breakout",
        entry_price=150.50,
        stop_loss=145.99,
        target_price=160.00,
        confidence_score=0.85,
        market_data_json={"price": 150.50, "volume": 1000000},
        is_read=False,
    )
    db_session.add(alert)
    await db_session.commit()
    await db_session.refresh(alert)
    return alert


@pytest_asyncio.fixture
async def multiple_alerts(db_session: AsyncSession, sample_rule: Rule) -> list[Alert]:
    """Create multiple alerts for pagination testing."""
    alerts = []
    symbols = ["AAPL", "GOOGL", "MSFT", "TSLA", "NVDA"]
    # Valid SetupType enum values: breakout, volume_spike, gap_up, gap_down, momentum
    setup_types = ["breakout", "momentum", "volume_spike", "breakout", "momentum"]

    for i, (symbol, setup_type) in enumerate(zip(symbols, setup_types)):
        alert = Alert(
            rule_id=sample_rule.id,
            symbol=symbol,
            timestamp=datetime.utcnow(),
            setup_type=setup_type,
            entry_price=100.0 + i * 10,
            stop_loss=95.0 + i * 10,
            target_price=110.0 + i * 10,
            confidence_score=0.7 + i * 0.05,
            is_read=i % 2 == 0,  # Alternate read status
        )
        db_session.add(alert)
        alerts.append(alert)

    await db_session.commit()
    for alert in alerts:
        await db_session.refresh(alert)
    return alerts


@pytest_asyncio.fixture
async def sample_watchlist_item(db_session: AsyncSession) -> Watchlist:
    """Create a sample watchlist item."""
    item = Watchlist(
        symbol="AAPL",
        notes="Test watchlist item",
        is_active=True,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    return item


@pytest_asyncio.fixture
async def multiple_watchlist_items(db_session: AsyncSession) -> list[Watchlist]:
    """Create multiple watchlist items."""
    items = []
    symbols = ["AAPL", "GOOGL", "MSFT", "TSLA"]

    for symbol in symbols:
        item = Watchlist(
            symbol=symbol,
            notes=f"Watching {symbol}",
            is_active=True,
        )
        db_session.add(item)
        items.append(item)

    await db_session.commit()
    for item in items:
        await db_session.refresh(item)
    return items
