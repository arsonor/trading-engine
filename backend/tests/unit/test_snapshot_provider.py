"""Tests for the market-snapshot providers.

The fixture provider is what stands in for live pre-market data in V1. Its relative-value
mode is the interesting part: a scenario expressed as "gaps up 7%" stays a 7% gap after
tomorrow's reference refresh, whereas a hardcoded price silently drifts out of the band
and the scenario quietly stops testing what it claims to.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.scanner.candidate import Candidate
from app.services.scanner.snapshot import (
    SOURCE_FIXTURE,
    FixtureSnapshotProvider,
    FmpLiveSnapshotProvider,
    MarketSnapshot,
)

AS_OF = datetime(2026, 7, 28, 8, 45)
# The live provider works in market time; these tests pin an ET-aware clock.
ET = ZoneInfo("America/New_York")
LIVE_AS_OF = datetime(2026, 7, 28, 8, 45, tzinfo=ET)


def candidate(ticker="TEST", close=100.0, avg_vol=1_000_000.0) -> Candidate:
    return Candidate(
        ticker=ticker, price_close_yesterday=close, volume_avg_20d=avg_vol
    )


async def test_absolute_values_are_used_verbatim():
    provider = FixtureSnapshotProvider(
        scenario={"snapshots": {"TEST": {"price": 123.45, "premarket_volume": 42_000}}}
    )

    snapshots = await provider.get_snapshots([candidate()], AS_OF)

    assert snapshots["TEST"].price == 123.45
    assert snapshots["TEST"].volume_premarket_accumulated == 42_000
    assert snapshots["TEST"].source == SOURCE_FIXTURE


RELATIVE_ENTRY = {"gap_pct": 7.0, "premarket_volume_ratio": 0.25}


async def test_gap_pct_is_resolved_against_the_tickers_own_prior_close():
    provider = FixtureSnapshotProvider(scenario={"snapshots": {"TEST": RELATIVE_ENTRY}})

    snapshots = await provider.get_snapshots([candidate(close=200.0)], AS_OF)

    assert snapshots["TEST"].price == pytest.approx(214.0)


async def test_gap_pct_stays_a_7_percent_gap_when_reference_data_moves():
    """The point of relative scenarios: a nightly refresh must not silently invalidate
    the scenario."""
    provider = FixtureSnapshotProvider(scenario={"snapshots": {"TEST": RELATIVE_ENTRY}})

    today = await provider.get_snapshots([candidate(close=100.0)], AS_OF)
    tomorrow = await provider.get_snapshots([candidate(close=180.0)], AS_OF)

    def gap(snapshot: MarketSnapshot, close: float) -> float:
        return (snapshot.price - close) / close * 100

    assert gap(today["TEST"], 100.0) == pytest.approx(7.0)
    assert gap(tomorrow["TEST"], 180.0) == pytest.approx(7.0)


async def test_volume_ratio_is_the_inverse_of_simple_rvol():
    """A ratio of 0.25 must make the real calculator report 25% — the scenario supplies
    volume, it does not get to declare the RVOL."""
    from app.services.scanner.rvol import RvolContext, SimpleRvol

    provider = FixtureSnapshotProvider(
        scenario={"snapshots": {"TEST": {"gap_pct": 5.0, "premarket_volume_ratio": 0.25}}}
    )
    cand = candidate(avg_vol=2_000_000.0)

    snapshots = await provider.get_snapshots([cand], AS_OF)
    assert snapshots["TEST"].volume_premarket_accumulated == 500_000

    computed = SimpleRvol().compute(
        RvolContext(
            ticker="TEST",
            volume_premarket_accumulated=snapshots["TEST"].volume_premarket_accumulated,
            volume_avg_20d=cand.volume_avg_20d,
        )
    )
    assert computed.rvol_pct == pytest.approx(25.0)


async def test_tickers_absent_from_the_scenario_are_omitted_not_zero_filled():
    provider = FixtureSnapshotProvider(scenario={"snapshots": {"TEST": {"price": 100.0,
                                                                       "premarket_volume": 1}}})

    snapshots = await provider.get_snapshots([candidate(), candidate("OTHER")], AS_OF)

    assert set(snapshots) == {"TEST"}


async def test_relative_spec_without_reference_data_is_skipped_with_a_warning(caplog):
    """A gap_pct entry needs a prior close. Missing one must skip the ticker, never
    produce a snapshot built on a guessed baseline."""
    provider = FixtureSnapshotProvider(scenario={"snapshots": {"TEST": {"gap_pct": 5.0}}})

    snapshots = await provider.get_snapshots(
        [Candidate(ticker="TEST", price_close_yesterday=None)], AS_OF
    )

    assert snapshots == {}


async def test_incomplete_scenario_entry_is_skipped():
    provider = FixtureSnapshotProvider(scenario={"snapshots": {"TEST": {"gap_pct": 5.0}}})

    # gap_pct resolves, but there is no volume key at all.
    snapshots = await provider.get_snapshots([candidate()], AS_OF)

    assert snapshots == {}


def test_scenario_declares_its_own_as_of():
    provider = FixtureSnapshotProvider(
        scenario={"as_of": "2026-07-28T09:25:00-04:00", "snapshots": {}}
    )

    assert provider.declared_as_of.hour == 9
    assert provider.declared_as_of.minute == 25


def test_missing_scenario_file_says_what_to_do(tmp_path):
    with pytest.raises(FileNotFoundError, match="--snapshot-file"):
        FixtureSnapshotProvider(tmp_path / "nope.json")


def test_snapshot_rejects_impossible_values():
    with pytest.raises(ValueError, match="price must be positive"):
        MarketSnapshot("TEST", 0.0, 100, AS_OF, SOURCE_FIXTURE)

    with pytest.raises(ValueError, match="cannot be negative"):
        MarketSnapshot("TEST", 10.0, -1, AS_OF, SOURCE_FIXTURE)


# ============================================ the live provider (Phase 4C)


class _Bar:
    """Shape of an FMP intraday row: naive market-local stamp at the bar's OPENING edge."""

    def __init__(self, hour, minute, volume, close=10.0, day=28, month=7):
        self.date = datetime(2026, month, day, hour, minute)
        self.volume = volume
        self.close = close


class _FakeClient:
    """Replays canned bars per ticker. `raises` makes one ticker fail."""

    def __init__(self, bars_by_ticker, raises=None):
        self._bars = bars_by_ticker
        self._raises = raises or {}
        self.calls = []
        self.closed = False

    async def get_intraday_bars(self, symbol, **kwargs):
        self.calls.append(symbol)
        if symbol in self._raises:
            raise self._raises[symbol]
        return self._bars.get(symbol, [])

    async def aclose(self):
        self.closed = True


async def test_live_provider_sums_bars_because_volume_is_per_bar():
    """Measured in 4A: consecutive bars FALL (30,243 -> 9,965 -> 2,822). Reading the newest
    bar's volume would report the last five minutes as the whole session."""
    client = _FakeClient({"LOWF": [
        _Bar(4, 0, 30_243), _Bar(4, 5, 9_965), _Bar(4, 10, 2_822),
    ]})
    provider = FmpLiveSnapshotProvider(client=client)

    snaps = await provider.get_snapshots([candidate("LOWF")], LIVE_AS_OF)

    assert snaps["LOWF"].volume_premarket_accumulated == 43_030


async def test_empty_array_means_not_trading_not_an_error_and_not_a_zero():
    """4A watched EROC return [] three times and then convert to real bars. A zero here
    would read as measured stillness and hand RVOL a real-looking 0%."""
    client = _FakeClient({"LOWF": []})
    provider = FmpLiveSnapshotProvider(client=client)

    snaps = await provider.get_snapshots([candidate("LOWF")], LIVE_AS_OF)

    assert snaps == {}, "absent, never zero-filled"
    assert provider.not_trading == ["LOWF"]
    assert provider.failures == {}, "not trading is not a failure"


async def test_provisional_bars_are_excluded_and_the_cut_off_is_recorded():
    """The newest bars are still being revised, so they are dropped and the honest
    cut-off travels with the snapshot for RVOL to divide at."""
    as_of = datetime(2026, 7, 28, 4, 20, tzinfo=ET)
    client = _FakeClient({"LOWF": [
        _Bar(4, 0, 100), _Bar(4, 5, 100), _Bar(4, 10, 100), _Bar(4, 15, 100),
    ]})
    provider = FmpLiveSnapshotProvider(client=client, settle_minutes=7)

    snap = (await provider.get_snapshots([candidate("LOWF")], as_of))["LOWF"]

    # 04:00 closes 04:05 (+7 = 04:12, settled); 04:05 closes 04:10 (+7 = 04:17, settled);
    # 04:10 closes 04:15 (+7 = 04:22, NOT yet); 04:15 still forming.
    assert snap.bars_used == 2
    assert snap.volume_premarket_accumulated == 200
    assert snap.provisional_bars_excluded == 2
    assert snap.settled_through == datetime(2026, 7, 28, 4, 10, tzinfo=ET)


async def test_bars_after_the_scan_moment_are_ignored():
    """A pass simulated at 06:00 must not see 09:00 bars merely because the request
    returned the whole day."""
    as_of = datetime(2026, 7, 28, 6, 0, tzinfo=ET)
    client = _FakeClient({"LOWF": [_Bar(4, 0, 100), _Bar(9, 0, 999_999)]})
    provider = FmpLiveSnapshotProvider(client=client, settle_minutes=0)

    snap = (await provider.get_snapshots([candidate("LOWF")], as_of))["LOWF"]

    assert snap.volume_premarket_accumulated == 100


async def test_one_failing_ticker_does_not_fail_the_scan():
    client = _FakeClient(
        {"LOWF": [_Bar(4, 0, 500)]},
        raises={"BUST": RuntimeError("upstream exploded")},
    )
    provider = FmpLiveSnapshotProvider(client=client, settle_minutes=0)

    snaps = await provider.get_snapshots(
        [candidate("LOWF"), candidate("BUST")], LIVE_AS_OF
    )

    assert set(snaps) == {"LOWF"}
    assert "BUST" in provider.failures
    assert "upstream exploded" in provider.failures["BUST"]


async def test_an_injected_client_is_not_closed_by_the_provider():
    """The pipeline shares one client across the whole scan; closing it here would break
    every later call."""
    client = _FakeClient({"LOWF": [_Bar(4, 0, 1)]})

    await FmpLiveSnapshotProvider(client=client, settle_minutes=0).get_snapshots(
        [candidate("LOWF")], LIVE_AS_OF
    )

    assert client.closed is False


def test_committed_golden_scenario_loads(golden_snapshot_provider):
    assert golden_snapshot_provider.name == "golden_session"
    assert "LOWF" in golden_snapshot_provider.tickers()
    assert golden_snapshot_provider.declared_as_of is not None
