"""Data-quality suppression in the risk filters.

## Why this rejects rather than flags

Phase 4C recorded these tickers as integrity findings and let them through. That is the
wrong shape for this specific problem: `upside_pct` is the sort key for the candidate list,
so a ticker with a 540% upside does not land somewhere in the middle where a warning might
be read — it lands **first**. The end user's opening impression of the product would be its
least defensible row.

## What was actually wrong, and what was not

The 4C hypothesis was that FMP served unadjusted history across reverse splits. Measured
8 August 2026, that is false: `historical-price-eod/full` is already split-adjusted, and
five of the seven flagged tickers had never split. FFAI really did fall 32.06 -> 4.38 in
twenty sessions.

So the arithmetic is right and the data is right, and neither can be fixed — which is
exactly why a *filter* is the only available answer. A 50-day average seven times the price
is where the stock used to trade, not something pulling it back.

These are risk filters per `docs/CLAUDE.md` §4.3, which blocks an alert regardless of stage
outcome. Stage 3 still computes upside exactly as before.
"""

import pytest

from app.services.scanner.candidate import STAGE_RISK, Candidate
from app.services.scanner.profiles import production_profile
from app.services.scanner.risk import (
    REASON_IMPLAUSIBLE_UPSIDE,
    REASON_PRICE_REGIME_BREAK,
    MarketTape,
    apply_risk_filters,
)

NEUTRAL = MarketTape(state="neutral", detail="test", is_available=True)


def candidate(
    ticker="TEST",
    price=10.0,
    close=10.0,
    upside=8.0,
    high_20d=11.0,
    avg_vol=1_000_000.0,
) -> Candidate:
    c = Candidate(
        ticker=ticker,
        price_close_yesterday=close,
        volume_avg_20d=avg_vol,
        high_20d=high_20d,
    )
    c.price_premarket_current = price
    c.upside_pct = upside
    c.nearest_resistance = price * (1 + upside / 100) if upside is not None else None
    c.resistance_source = "sma_50"
    return c


def run(*candidates):
    return apply_risk_filters(list(candidates), production_profile(), NEUTRAL)


# ------------------------------------------------------------------ the ordinary case


def test_a_normal_candidate_survives():
    outcome = run(candidate())

    assert [c.ticker for c in outcome.survivors] == ["TEST"]
    assert outcome.rejections == []


def test_a_large_but_plausible_upside_survives():
    """A post-crash retrace toward the 20-day high can legitimately offer 50-80%. The
    ceiling removes the meaningless tail, not the strategy's own upside cases."""
    outcome = run(candidate(upside=80.0, high_20d=12.0))

    assert len(outcome.survivors) == 1


# ------------------------------------------------------------------ implausible upside


def test_ffai_shaped_upside_is_rejected_with_a_named_reason():
    """FFAI as it actually appeared: 540% upside, sorted to the top of the list."""
    outcome = run(candidate("FFAI", price=4.83, close=4.63, upside=540.64, high_20d=32.17))

    assert outcome.survivors == []
    assert len(outcome.rejections) == 1
    rejection = outcome.rejections[0]
    assert rejection.stage == STAGE_RISK
    assert rejection.reason == REASON_IMPLAUSIBLE_UPSIDE
    assert "540" in rejection.detail


def test_the_upside_ceiling_is_configurable(monkeypatch):
    from app.config import Settings
    from app.services.scanner import risk as risk_module

    monkeypatch.setattr(risk_module, "get_settings", lambda: Settings(
        database_url="postgresql+asyncpg://u:p@localhost:5432/db", scan_upside_max=20.0
    ))

    outcome = run(candidate(upside=50.0, high_20d=11.0))

    assert outcome.rejections[0].reason == REASON_IMPLAUSIBLE_UPSIDE


def test_a_null_upside_is_not_rejected_by_the_ceiling():
    """Null upside is the documented breakout case (docs/CLAUDE.md §4.3), not a fault.
    Stage 3 already decides what to do with it; the ceiling must not second-guess that."""
    outcome = run(candidate(upside=None, high_20d=11.0))

    assert len(outcome.survivors) == 1


# ------------------------------------------------------------------ price regime break


def test_a_collapsed_price_is_rejected_even_when_upside_looks_reasonable():
    """The second, independent trip-wire. A ticker can show a modest upside to a NEAR
    resistance while its 20-day high still says the price regime has gone — WETO's high was
    16.8x its close. The reference data is correct and the collapse is real; the resistance
    levels are still meaningless."""
    outcome = run(candidate("WETO", price=5.77, close=5.77, upside=9.0, high_20d=97.0))

    assert outcome.survivors == []
    assert outcome.rejections[0].reason == REASON_PRICE_REGIME_BREAK
    assert "16.8x" in outcome.rejections[0].detail


def test_the_regime_ratio_is_configurable(monkeypatch):
    from app.config import Settings
    from app.services.scanner import risk as risk_module

    monkeypatch.setattr(risk_module, "get_settings", lambda: Settings(
        database_url="postgresql+asyncpg://u:p@localhost:5432/db",
        scan_price_regime_break_ratio=1.5,
    ))

    outcome = run(candidate(close=10.0, high_20d=20.0, upside=8.0))

    assert outcome.rejections[0].reason == REASON_PRICE_REGIME_BREAK


def test_a_missing_high_does_not_reject():
    """Absent reference data is a different problem with its own handling. This filter
    must not turn 'unknown' into 'bad'."""
    outcome = run(candidate(high_20d=None))

    assert len(outcome.survivors) == 1


# ------------------------------------------------------------------ reporting


def test_data_quality_rejections_are_distinguishable_from_ordinary_ones():
    """'3 candidates suppressed for implausible reference data' is information; a silent
    drop is not. The reasons are named constants so the CLI and scan_runs can separate
    them from a gap or rvol rejection."""
    from app.services.scanner.risk import DATA_QUALITY_REASONS

    outcome = run(
        candidate("GOOD"),
        candidate("FFAI", price=4.83, close=4.63, upside=540.64, high_20d=32.17),
        candidate("CHEAP", price=0.50, close=0.50, upside=8.0, high_20d=0.55),
    )

    quality = [r for r in outcome.rejections if r.reason in DATA_QUALITY_REASONS]
    other = [r for r in outcome.rejections if r.reason not in DATA_QUALITY_REASONS]

    assert [r.ticker for r in quality] == ["FFAI"]
    assert [r.ticker for r in other] == ["CHEAP"], "the price floor is not a data-quality issue"
    assert [c.ticker for c in outcome.survivors] == ["GOOD"]


@pytest.mark.parametrize(
    "ticker,close,high,upside",
    [
        ("FFAI", 4.63, 32.17, 540.64),
        ("WETO", 5.77, 97.00, 120.0),
        ("CAPR", 4.18, 22.58, 95.0),
        ("VEEE", 9.19, 55.49, 60.0),
        ("ADVB", 7.44, 24.23, 40.0),
    ],
)
def test_every_ticker_the_live_pass_flagged_is_now_suppressed(ticker, close, high, upside):
    """The regression set, taken from the 7 August 2026 live pass. These are the rows the
    end user would otherwise have seen at the top of the list."""
    outcome = run(candidate(ticker, price=close, close=close, upside=upside, high_20d=high))

    assert outcome.survivors == [], f"{ticker} should not reach the alert list"
