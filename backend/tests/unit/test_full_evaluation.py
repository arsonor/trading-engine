"""Follow-up D — evaluating every stage for every ticker must decide nothing new.

The change exists because a ticker rejected on gap never had its RVOL computed, so
Phase 6's threshold sweep could only report it as unresolved — 94.7% of the gap-tested
population at the eight authoritative passes of 13-21 August 2026. It costs no API calls
and no queries: the snapshot fan-out already covers every Stage-1 ticker and the profile
map is already bulk-loaded.

**The property that matters is negative**: turning full evaluation on must not change
which tickers become candidates, or why the others were rejected. The code is shaped so
that this is true by construction — both evaluation passes run *after* their stage's
decision loop and append neither survivors nor rejections — and this file pins it as
behaviour, in the same spirit as the tiered-cadence test that runs 09:25 under two
cadences and asserts one candidate set.
"""

from datetime import datetime

import pytest

from app.services.scanner.candidate import STAGE_2, Candidate
from app.services.scanner.profiles import production_profile
from app.services.scanner.rvol import SimpleRvol
from app.services.scanner.snapshot import MarketSnapshot
from app.services.scanner.stages import stage_2_momentum, stage_3_room_to_run

AS_OF = datetime(2026, 7, 28, 9, 25)


@pytest.fixture
def profile():
    return production_profile()


def candidate(ticker: str, **overrides) -> Candidate:
    base = {
        "ticker": ticker,
        "static_float": 40_000_000,
        "volume_avg_20d": 1_000_000.0,
        "price_close_yesterday": 100.0,
        "high_yesterday": 101.0,
        "high_20d": 120.0,
        "sma_50": 99.0,
        "sma_200": 95.0,
    }
    base.update(overrides)
    return Candidate(**base)


def population() -> list[Candidate]:
    """One ticker per outcome the funnel can produce."""
    return [
        candidate("PASS"),  # gap 5%, rvol 25% -> survives Stage 2
        candidate("FLAT"),  # gap 1% -> rejected below the band
        # gap 20% -> rejected above the band. `high_20d` is lifted clear of its 120.0
        # price on purpose: at the default 120.0 it would ALSO be a legitimate "above
        # every level" ticker, and this case needs to isolate the gap rejection.
        candidate("BLOW", high_20d=140.0),
        candidate("SLOW"),  # gap 5%, rvol exactly 10% -> rejected on RVOL
        candidate("DARK"),  # no snapshot at all -> nothing is computable
    ]


def snapshots() -> dict[str, MarketSnapshot]:
    def snap(ticker: str, price: float, volume: float) -> MarketSnapshot:
        return MarketSnapshot(
            ticker=ticker,
            price=price,
            volume_premarket_accumulated=volume,
            as_of=AS_OF,
            source="fixture",
        )

    return {
        "PASS": snap("PASS", 105.0, 250_000),
        "FLAT": snap("FLAT", 101.0, 250_000),
        "BLOW": snap("BLOW", 120.0, 250_000),
        "SLOW": snap("SLOW", 105.0, 100_000),
        # DARK deliberately absent — the ticker is not trading pre-market.
    }


def run(full_evaluation: bool):
    stage1 = population()
    stage2 = stage_2_momentum(
        stage1, snapshots(), production_profile(), SimpleRvol(), AS_OF,
        full_evaluation=full_evaluation,
    )
    stage3 = stage_3_room_to_run(
        stage2.survivors,
        production_profile(),
        also_evaluate=stage1 if full_evaluation else None,
    )
    return stage1, stage2, stage3


# --------------------------------------------------------------- the negative property


def test_full_evaluation_does_not_change_the_candidate_set():
    """THE test. If this ever fails, the flag is not an evidence setting any more."""
    _, off_2, off_3 = run(full_evaluation=False)
    _, on_2, on_3 = run(full_evaluation=True)

    assert [c.ticker for c in on_2.survivors] == [c.ticker for c in off_2.survivors]
    assert [c.ticker for c in on_3.survivors] == [c.ticker for c in off_3.survivors]
    assert [c.ticker for c in on_3.survivors] == ["PASS"]


def test_full_evaluation_does_not_change_why_anything_was_rejected():
    """The recorded reason must stay the FIRST gate that failed.

    A gap-rejected ticker is also, usually, evaluable on RVOL and headroom. If evaluating
    it re-labelled the rejection, the funnel would stop reconciling — live, that is the
    5,900 = 91 candidates + 5,809 rejections identity with no remainder on any session.
    """
    _, off_2, off_3 = run(full_evaluation=False)
    _, on_2, on_3 = run(full_evaluation=True)

    def reasons(*outcomes):
        return sorted(
            (r.ticker, r.stage, r.reason) for o in outcomes for r in o.rejections
        )

    assert reasons(on_2, on_3) == reasons(off_2, off_3)
    assert ("FLAT", STAGE_2, "gap outside band") in reasons(on_2, on_3)


def test_full_evaluation_adds_no_rejections_and_no_survivors():
    """Counting is how the funnel proves itself; the evaluation passes must not touch it."""
    _, off_2, off_3 = run(full_evaluation=False)
    _, on_2, on_3 = run(full_evaluation=True)

    assert len(on_2.rejections) == len(off_2.rejections)
    assert len(on_3.rejections) == len(off_3.rejections)
    assert len(on_2.survivors) == len(off_2.survivors)
    assert len(on_3.survivors) == len(off_3.survivors)


# --------------------------------------------------------------- the positive property


def test_gap_rejected_tickers_gain_rvol_and_headroom():
    """What the change is actually for: the sweep population stops being NULL."""
    stage1, _, _ = run(full_evaluation=True)
    by_ticker = {c.ticker: c for c in stage1}

    for ticker in ("FLAT", "BLOW"):
        assert by_ticker[ticker].gap_pct is not None
        assert by_ticker[ticker].rvol_pct == 25.0, f"{ticker} was rejected on gap alone"
        assert by_ticker[ticker].upside_pct is not None

    # SLOW cleared the gap band and was rejected on RVOL, so it only ever lacked headroom.
    assert by_ticker["SLOW"].upside_pct is not None


def test_without_full_evaluation_the_values_stay_null():
    """The old behaviour, kept honest — this is what the flag rolls back to."""
    stage1, _, _ = run(full_evaluation=False)
    by_ticker = {c.ticker: c for c in stage1}

    assert by_ticker["FLAT"].gap_pct is not None  # assigned before the band check
    assert by_ticker["FLAT"].rvol_pct is None
    assert by_ticker["FLAT"].upside_pct is None


def test_a_ticker_with_no_snapshot_stays_unevaluated():
    """NULL still means NOT EVALUATED, and there is still a population it applies to.

    No snapshot means no price, and no price means no gap, no RVOL and no headroom. No
    setting can conjure those, which is why `sweep_limitations()` survives Follow-up D
    rather than being deleted with it.
    """
    stage1, _, _ = run(full_evaluation=True)
    dark = {c.ticker: c for c in stage1}["DARK"]

    assert dark.gap_pct is None
    assert dark.rvol_pct is None
    assert dark.upside_pct is None
    assert dark.nearest_resistance is None


def test_headroom_is_still_null_when_the_price_is_above_every_level():
    """The breakout convention is a rejection, not a missing measurement — and evaluating
    a rejected ticker must not invent a value for it either.

    `docs/CLAUDE.md` 4.3 keeps these columns nullable precisely so reversing that
    convention stays a one-branch change. Filling them in here would quietly remove that.
    """
    high_flyer = candidate("BRKO", price_close_yesterday=100.0)
    snaps = {
        "BRKO": MarketSnapshot(
            ticker="BRKO",
            price=130.0,  # above high_yesterday, high_20d, sma_50 and sma_200
            volume_premarket_accumulated=250_000,
            as_of=AS_OF,
            source="fixture",
        )
    }

    stage_2_momentum(
        [high_flyer], snaps, production_profile(), SimpleRvol(), AS_OF,
        full_evaluation=True,
    )
    stage_3_room_to_run([], production_profile(), also_evaluate=[high_flyer])

    assert high_flyer.upside_pct is None
    assert high_flyer.nearest_resistance is None
