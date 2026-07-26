"""Replay the committed real FMP recordings.

Everything else in the suite runs on synthetic fixtures, which proves the code is
self-consistent but not that it matches FMP. These tests replay responses captured from
the live free-tier API (`scripts/record_fmp_fixtures.py`) so a change in FMP's actual
shape — a renamed field, a different error format — shows up here rather than in
production. No network access: the recordings are on disk.
"""

import pytest

from app.services.fmp.errors import MalformedResponse, SymbolNotAvailable
from app.services.fmp.fixtures import FixtureFmpClient, FixtureStore
from app.services.reference.metrics import compute_reference_metrics

RECORDED_SYMBOLS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMD"]


@pytest.fixture
def recorded_client() -> FixtureFmpClient:
    store = FixtureStore()  # FMP_FIXTURES_DIR, i.e. tests/fixtures/fmp
    if not store.keys():
        pytest.skip("No recorded FMP fixtures; run scripts/record_fmp_fixtures.py")
    return FixtureFmpClient(store=store)


@pytest.mark.parametrize("symbol", RECORDED_SYMBOLS)
async def test_real_eod_history_parses(recorded_client, symbol):
    bars = await recorded_client.get_eod_history(symbol)

    assert len(bars) > 200  # enough depth for SMA-200
    assert bars[0].date > bars[-1].date  # newest first
    assert all(b.close > 0 and b.volume >= 0 for b in bars)


@pytest.mark.parametrize("symbol", RECORDED_SYMBOLS)
async def test_real_history_yields_a_complete_metric_set(recorded_client, symbol):
    metrics = compute_reference_metrics(await recorded_client.get_eod_history(symbol))

    assert metrics.is_complete
    assert metrics.sma_50 is not None
    assert metrics.sma_200 is not None
    assert metrics.high_20d >= metrics.high_yesterday
    assert metrics.volume_avg_20d > 0


@pytest.mark.parametrize("symbol", RECORDED_SYMBOLS)
async def test_real_shares_float_parses(recorded_client, symbol):
    shares = await recorded_client.get_shares_float(symbol)

    assert shares.symbol == symbol
    assert shares.float_shares and shares.float_shares > 0
    assert shares.outstanding_shares and shares.outstanding_shares >= shares.float_shares


async def test_free_tier_symbol_restriction_is_reproduced(recorded_client):
    """The real 402 + plain-text body, replayed. This is the branch that decides
    whether a restricted ticker is skipped or blows up the run."""
    with pytest.raises(SymbolNotAvailable) as exc_info:
        await recorded_client.get_eod_history("SNDL")

    assert "not available under your current subscription" in str(exc_info.value)


async def test_free_tier_megacaps_all_fail_the_real_stage_1_float_filter(recorded_client):
    """Documents the V1 constraint that forces Phase 2's demo threshold profile: every
    symbol the free tier serves has a float far above the 75M production cap."""
    floats = {}
    for symbol in RECORDED_SYMBOLS:
        shares = await recorded_client.get_shares_float(symbol)
        floats[symbol] = shares.float_shares

    assert all(value > 75_000_000 for value in floats.values()), floats


async def test_degenerate_recordings_raise_the_right_errors(recorded_client):
    with pytest.raises(SymbolNotAvailable):
        await recorded_client.get_eod_history("__EMPTY__")

    with pytest.raises(MalformedResponse):
        await recorded_client.get_eod_history("__MALFORMED__")

    shares = await recorded_client.get_shares_float("__NOFLOAT__")
    assert shares.float_shares is None
