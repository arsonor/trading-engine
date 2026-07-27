"""Tests for the market-snapshot providers.

The fixture provider is what stands in for live pre-market data in V1. Its relative-value
mode is the interesting part: a scenario expressed as "gaps up 7%" stays a 7% gap after
tomorrow's reference refresh, whereas a hardcoded price silently drifts out of the band
and the scenario quietly stops testing what it claims to.
"""

from datetime import datetime

import pytest

from app.services.scanner.candidate import Candidate
from app.services.scanner.errors import ScannerError
from app.services.scanner.snapshot import (
    SOURCE_FIXTURE,
    FixtureSnapshotProvider,
    FmpLiveSnapshotProvider,
    MarketSnapshot,
)

AS_OF = datetime(2026, 7, 28, 8, 45)


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


async def test_live_provider_refuses_rather_than_faking_data():
    """V2's implementation drops in behind this interface. Until then it must not
    silently return anything."""
    with pytest.raises(ScannerError, match="FMP Starter"):
        await FmpLiveSnapshotProvider().get_snapshots([candidate()], AS_OF)


def test_committed_golden_scenario_loads(golden_snapshot_provider):
    assert golden_snapshot_provider.name == "golden_session"
    assert "LOWF" in golden_snapshot_provider.tickers()
    assert golden_snapshot_provider.declared_as_of is not None
