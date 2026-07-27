"""Pytest configuration and fixtures for testing."""

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.main import app
from app.models import Alert, ReferenceData, Rule, Universe, Watchlist
from app.services.fmp.client import EP_EOD_FULL, EP_SHARES_FLOAT
from app.services.fmp.fixtures import FixtureFmpClient, FixtureStore
from app.services.scanner.snapshot import FixtureSnapshotProvider

# Test database URL (in-memory SQLite)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    """Create and dispose test engine for each test."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        future=True,
    )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def test_session_factory(test_engine):
    """Create a session factory for integration tests that need to patch async_session_maker."""
    # Create all tables
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    yield session_factory

    # Drop all tables after test
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def db_session(test_session_factory) -> AsyncGenerator[AsyncSession, None]:
    """Create a fresh database session for each test."""
    async with test_session_factory() as session:
        yield session


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


# ============== FMP Fixture Replay ==============
#
# Tests never touch live FMP. These build a synthetic fixture store on disk so the replay
# client — which shares every line of parsing and validation with the live client — can
# serve deterministic responses.

FIXTURE_LATEST_DATE = date(2026, 7, 24)
FIXTURE_BAR_COUNT = 260
FIXTURE_SYMBOLS = {
    # symbol -> (starting close, float shares, outstanding shares)
    "AAPL": (100.0, 15_000_000_000, 15_400_000_000),
    "MSFT": (300.0, 7_400_000_000, 7_500_000_000),
    # A deliberately low-float name so Stage-1-style queries have something to select.
    "SMLC": (12.0, 40_000_000, 55_000_000),
    # Present in EOD but with no float figures at all — the null-tolerant path.
    "NOFLT": (25.0, None, None),
}


def make_eod_rows(close_start: float, count: int = FIXTURE_BAR_COUNT) -> list[dict]:
    """Daily bars, newest first: close rises 0.5/session going forward, high = close + 1."""
    rows = []
    for i in range(count):
        close = close_start + (count - 1 - i) * 0.5
        rows.append(
            {
                "date": (FIXTURE_LATEST_DATE - timedelta(days=i)).isoformat(),
                "open": round(close - 0.25, 4),
                "high": round(close + 1.0, 4),
                "low": round(close - 1.0, 4),
                "close": round(close, 4),
                "volume": 1_000_000,
            }
        )
    return rows


@pytest.fixture
def fmp_fixture_store(tmp_path) -> FixtureStore:
    """A fixture store populated with deterministic synthetic FMP recordings."""
    store = FixtureStore(tmp_path / "fmp")

    for symbol, (close_start, float_shares, outstanding) in FIXTURE_SYMBOLS.items():
        store.save(EP_EOD_FULL, {"symbol": symbol}, 200, make_eod_rows(close_start))
        row: dict = {"symbol": symbol, "date": FIXTURE_LATEST_DATE.isoformat()}
        if float_shares is not None:
            row["floatShares"] = float_shares
            row["outstandingShares"] = outstanding
        store.save(EP_SHARES_FLOAT, {"symbol": symbol}, 200, [row])

    # A symbol the free tier refuses, recorded exactly as FMP reports it.
    restricted = {"Error Message": "This endpoint is limited to the following symbols: AAPL, MSFT"}
    for endpoint in (EP_EOD_FULL, EP_SHARES_FLOAT):
        store.save(endpoint, {"symbol": "SNDL"}, 403, restricted)

    # Degenerate responses that the pipeline has to survive.
    store.save(EP_EOD_FULL, {"symbol": "EMPTY"}, 200, [])
    store.save(
        EP_EOD_FULL,
        {"symbol": "BROKEN"},
        200,
        [{"date": "2026-07-24", "open": 10.0, "high": "not-a-number"}],
    )
    return store


@pytest.fixture
def fixture_fmp_client(fmp_fixture_store) -> FixtureFmpClient:
    """Replay client backed by the synthetic store. Makes no network calls."""
    return FixtureFmpClient(store=fmp_fixture_store)


# ============== Scanner Golden Reference Data ==============
#
# Synthetic reference data whose every derived figure is an exact, hand-checkable number.
# Pairs with tests/fixtures/snapshots/golden_session.json — see that file for the
# expectation attached to each ticker, and test_scanner_pipeline.py for the full funnel.
#
# ticker  float   avg_vol    close_y  high_y  high_20d  sma_50  sma_200   what it proves
# LOWF     40M    1,000,000   100.00  101.00   120.000   105.0    90.0    clean survivor
# EDGE     40M    1,000,000   100.00  101.00   108.665    99.0    95.0    all three boundaries at once
# BRKO     40M    1,000,000   100.00  101.00   104.000    99.0    95.0    gapped above every level
# NEAR     40M    1,000,000   100.00  101.00   108.000    99.0    95.0    resistance too close
# SLOW     40M    1,000,000   100.00  101.00   120.000    99.0    95.0    rvol exactly at threshold
# FLAT     40M    1,000,000   100.00  101.00   120.000    99.0    95.0    gap under the floor
# BLOW     40M    1,000,000   100.00  101.00   130.000    99.0    95.0    gap over the ceiling
# BIGF    900M    1,000,000   100.00  101.00   120.000    99.0    95.0    float fails Stage 1
# THIN     40M      400,000   100.00  101.00   120.000    99.0    95.0    avg volume fails Stage 1
# NOFL     None   1,000,000   100.00  101.00   120.000    99.0    95.0    null float fails Stage 1
# PENN     40M    1,000,000     1.50    1.55     2.000     1.6     1.4    price floor fails Stage 1

GOLDEN_REFERENCE_ROWS = [
    # (ticker, float, avg_vol, close_y, high_y, high_20d, sma_50, sma_200)
    ("LOWF", 40_000_000, 1_000_000.0, 100.0, 101.0, 120.0, 105.0, 90.0),
    ("EDGE", 40_000_000, 1_000_000.0, 100.0, 101.0, 108.665, 99.0, 95.0),
    ("BRKO", 40_000_000, 1_000_000.0, 100.0, 101.0, 104.0, 99.0, 95.0),
    ("NEAR", 40_000_000, 1_000_000.0, 100.0, 101.0, 108.0, 99.0, 95.0),
    ("SLOW", 40_000_000, 1_000_000.0, 100.0, 101.0, 120.0, 99.0, 95.0),
    ("FLAT", 40_000_000, 1_000_000.0, 100.0, 101.0, 120.0, 99.0, 95.0),
    ("BLOW", 40_000_000, 1_000_000.0, 100.0, 101.0, 130.0, 99.0, 95.0),
    ("BIGF", 900_000_000, 1_000_000.0, 100.0, 101.0, 120.0, 99.0, 95.0),
    ("THIN", 40_000_000, 400_000.0, 100.0, 101.0, 120.0, 99.0, 95.0),
    ("NOFL", None, 1_000_000.0, 100.0, 101.0, 120.0, 99.0, 95.0),
    ("PENN", 40_000_000, 1_000_000.0, 1.5, 1.55, 2.0, 1.6, 1.4),
]

GOLDEN_SNAPSHOT_FILE = Path(__file__).parent / "fixtures" / "snapshots" / "golden_session.json"


@pytest_asyncio.fixture
async def golden_reference_data(test_session_factory):
    """Seed `universe` + `reference_data` with the golden fixture set."""
    async with test_session_factory() as session:
        for ticker, float_shares, avg_vol, close_y, high_y, high20, sma50, sma200 in (
            GOLDEN_REFERENCE_ROWS
        ):
            session.add(
                Universe(ticker=ticker, is_active=True, is_accessible_free_tier=True)
            )
            session.add(
                ReferenceData(
                    ticker=ticker,
                    static_float=float_shares,
                    volume_avg_20d=avg_vol,
                    price_close_yesterday=close_y,
                    high_yesterday=high_y,
                    high_20d=high20,
                    sma_50=sma50,
                    sma_200=sma200,
                    bars_used=260,
                    data_source="fixture",
                    computed_at=datetime.utcnow(),
                )
            )
        await session.commit()
    return GOLDEN_REFERENCE_ROWS


@pytest.fixture
def golden_snapshot_provider() -> FixtureSnapshotProvider:
    """Snapshot provider backed by the committed golden scenario."""
    return FixtureSnapshotProvider(GOLDEN_SNAPSHOT_FILE)


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
