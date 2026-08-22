"""The three filtration stages.

Boundary conventions are taken literally from `docs/CLAUDE.md` section 4.3 and pinned by
golden-case tests, because "gap >= 3.0" and "gap > 3.0" quietly produce different
candidate sets and nobody notices for months:

| Threshold        | Spec                     | Boundary value | Passes? |
|------------------|--------------------------|----------------|---------|
| `static_float`   | `< 75,000,000`           | exactly 75M    | NO      |
| `volume_avg_20d` | `> 500,000`              | exactly 500k   | NO      |
| `gap_pct`        | `3.0 <= gap <= 15.0`     | exactly 3.0    | YES     |
| `gap_pct`        | `3.0 <= gap <= 15.0`     | exactly 15.0   | YES     |
| `rvol_pct`       | `> 10.0`                 | exactly 10.0   | NO      |
| `upside_pct`     | `>= 5.5`                 | exactly 5.5    | YES     |

Null handling is uniformly conservative: a missing input rejects the ticker. A ticker with
no float is not a low-float ticker, and treating a null as a pass would put the least
verifiable names at the top of the alert list.

Percentages are compared at `COMPARISON_DP` decimal places. Comparing raw floats to a
threshold is a coin flip at the boundary — `105 * 1.055 - 105` gives an upside of
5.499999999999996, which would reject a candidate whose UI card reads "5.50%" against a
documented 5.5% bar. Rounding first makes the boundary deterministic and makes the
displayed number and the decision agree.
"""

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reference_data import ReferenceData
from app.models.universe import Universe
from app.services.scanner.candidate import (
    STAGE_2,
    STAGE_3,
    Candidate,
    Rejection,
    StageOutcome,
)
from app.services.scanner.errors import FeatureRequiresIntraday, InsufficientRvolData
from app.services.scanner.profile_store import VolumeProfile
from app.services.scanner.profiles import ThresholdProfile
from app.services.scanner.rvol import RvolCalculator, RvolContext
from app.services.scanner.snapshot import MarketSnapshot

logger = logging.getLogger(__name__)

# Decimal places used when comparing a computed percentage against a threshold. Far finer
# than any real threshold, coarse enough to erase IEEE-754 noise at the boundary.
COMPARISON_DP = 6


def at_precision(value: float) -> float:
    """Round a computed percentage to the comparison precision."""
    return round(value, COMPARISON_DP)


# --------------------------------------------------------------------------- Stage 1


async def stage_1_liquidity(
    session: AsyncSession,
    profile: ThresholdProfile,
    tickers: list[str] | None = None,
) -> list[Candidate]:
    """Structural liquidity, as a single SQL query against pre-computed reference data.

    This is what makes a universe-wide scan affordable: the expensive part (float, 20-day
    averages, SMAs) was computed by the nightly pipeline, so the morning scan is one
    indexed query rather than thousands of API calls.

    Every `IS NOT NULL` here is doing real work — see the module docstring on nulls.
    """
    stmt = (
        select(ReferenceData)
        .join(Universe, Universe.ticker == ReferenceData.ticker)
        .where(
            Universe.is_active.is_(True),
            ReferenceData.static_float.isnot(None),
            ReferenceData.static_float < profile.float_max,
            ReferenceData.volume_avg_20d.isnot(None),
            ReferenceData.volume_avg_20d > profile.avg_volume_min,
            ReferenceData.price_close_yesterday.isnot(None),
            ReferenceData.price_close_yesterday >= profile.price_floor,
        )
        .order_by(ReferenceData.ticker)
    )
    if tickers:
        stmt = stmt.where(ReferenceData.ticker.in_([t.upper() for t in tickers]))

    rows = (await session.execute(stmt)).scalars().all()
    return [_to_candidate(row) for row in rows]


async def stage_1_universe_size(
    session: AsyncSession, tickers: list[str] | None = None
) -> int:
    """How many tickers Stage 1 considered — the denominator for the stage counts."""
    stmt = (
        select(ReferenceData.ticker)
        .join(Universe, Universe.ticker == ReferenceData.ticker)
        .where(Universe.is_active.is_(True))
    )
    if tickers:
        stmt = stmt.where(ReferenceData.ticker.in_([t.upper() for t in tickers]))
    return len((await session.execute(stmt)).scalars().all())


def _to_candidate(row: ReferenceData) -> Candidate:
    return Candidate(
        ticker=row.ticker,
        static_float=row.static_float,
        volume_avg_20d=row.volume_avg_20d,
        price_close_yesterday=row.price_close_yesterday,
        high_yesterday=row.high_yesterday,
        high_20d=row.high_20d,
        sma_50=row.sma_50,
        sma_200=row.sma_200,
        reference_computed_at=row.computed_at,
        reference_source=row.data_source,
    )


# --------------------------------------------------------------------------- Stage 2


def stage_2_momentum(
    candidates: list[Candidate],
    snapshots: dict[str, MarketSnapshot],
    profile: ThresholdProfile,
    rvol_calculator: RvolCalculator,
    as_of: datetime,
    profiles: dict[str, VolumeProfile] | None = None,
    full_evaluation: bool = False,
) -> StageOutcome:
    """Gap and relative volume against live pre-market state.

    A `FeatureRequiresIntraday` from the calculator is deliberately *not* caught: if RVOL
    cannot be computed at all, every ticker would be rejected and the run would look like
    a quiet market. That must surface as a failed scan instead.

    `full_evaluation` (Follow-up D) adds a second pass that computes RVOL for the tickers
    this one rejected on gap, so Phase 5 can sweep the gap band over stored rows. It runs
    after every decision has been made and appends nothing to the outcome — see
    `_evaluate_remaining_rvol`.
    """
    outcome = StageOutcome()

    for candidate in candidates:
        vol_profile = (profiles or {}).get(candidate.ticker)
        snapshot = snapshots.get(candidate.ticker)
        if snapshot is None:
            outcome.rejections.append(
                Rejection(
                    candidate.ticker,
                    STAGE_2,
                    "no market snapshot",
                    "no pre-market price/volume available for this ticker",
                )
            )
            continue

        candidate.price_premarket_current = snapshot.price
        candidate.volume_premarket_accumulated = snapshot.volume_premarket_accumulated
        candidate.snapshot_source = snapshot.source

        if not candidate.price_close_yesterday:
            outcome.rejections.append(
                Rejection(candidate.ticker, STAGE_2, "no prior close", "cannot compute gap")
            )
            continue

        candidate.gap_pct = at_precision(
            (snapshot.price - candidate.price_close_yesterday)
            / candidate.price_close_yesterday
            * 100
        )

        # Inclusive at both ends, per the spec.
        if not (profile.gap_min <= candidate.gap_pct <= profile.gap_max):
            outcome.rejections.append(
                Rejection(
                    candidate.ticker,
                    STAGE_2,
                    "gap outside band",
                    f"gap {candidate.gap_pct:.2f}% not in "
                    f"[{profile.gap_min}, {profile.gap_max}]",
                )
            )
            continue

        try:
            _assign_rvol(candidate, snapshot, vol_profile, rvol_calculator, as_of)
        except InsufficientRvolData as exc:
            # Missing inputs are a per-ticker data problem: skip it, keep scanning.
            outcome.rejections.append(
                Rejection(candidate.ticker, STAGE_2, "rvol unavailable", str(exc))
            )
            continue
        except FeatureRequiresIntraday:
            raise  # scan-wide failure; see the docstring

        # Strictly greater, per the spec.
        if candidate.rvol_pct <= profile.rvol_min:
            outcome.rejections.append(
                Rejection(
                    candidate.ticker,
                    STAGE_2,
                    "rvol too low",
                    f"rvol {candidate.rvol_pct:.2f}% <= {profile.rvol_min}",
                )
            )
            continue

        outcome.survivors.append(candidate)

    if full_evaluation:
        _evaluate_remaining_rvol(candidates, snapshots, rvol_calculator, as_of, profiles or {})

    return outcome


def _assign_rvol(
    candidate: Candidate,
    snapshot: MarketSnapshot,
    vol_profile: VolumeProfile | None,
    rvol_calculator: RvolCalculator,
    as_of: datetime,
) -> None:
    """Compute RVOL and write it, with its provenance, onto the candidate.

    Extracted so the decision loop above and the evaluation pass below cannot drift. Two
    places assigning these fields differently is exactly the kind of divergence Phase 5
    would read as a real difference between tickers.
    """
    result = rvol_calculator.compute(
        RvolContext(
            ticker=candidate.ticker,
            volume_premarket_accumulated=snapshot.volume_premarket_accumulated,
            volume_avg_20d=candidate.volume_avg_20d,
            as_of=as_of,
            # The symmetry rule: the profile bucket is chosen from the instant the
            # numerator is actually complete to, not from the scan time. See
            # `_expected_volume_at` in rvol.py for why the difference matters.
            settled_through=snapshot.settled_through,
            premarket_volume_profile=(vol_profile.buckets if vol_profile else {}),
            profile_sessions_sampled=(vol_profile.sessions_sampled if vol_profile else None),
        )
    )

    candidate.rvol_pct = at_precision(result.rvol_pct)
    candidate.rvol_mode = result.mode
    candidate.rvol_is_approximate = result.is_approximate
    candidate.rvol_detail = result.detail
    # Provenance travels with the candidate to the alert. `rvol_mode` above already
    # records whether the normalized path degraded; these say what data it saw.
    candidate.bars_settled_through = snapshot.settled_through
    candidate.provisional_bars_excluded = snapshot.provisional_bars_excluded
    candidate.profile_sessions_sampled = vol_profile.sessions_sampled if vol_profile else None


def _evaluate_remaining_rvol(
    candidates: list[Candidate],
    snapshots: dict[str, MarketSnapshot],
    rvol_calculator: RvolCalculator,
    as_of: datetime,
    profiles: dict[str, VolumeProfile],
) -> None:
    """Fill RVOL for tickers the decision loop rejected on gap. Decides nothing.

    A ticker rejected on gap has never had its RVOL computed, so a Phase 5 sweep that
    widens the gap band can only report it as *unresolved* — never as passing or failing.
    Measured at the eight authoritative passes of 13-21 August 2026, that is **94.7% of
    everything gap-tested** (5,431 of 5,738), which is most of the population the sweep
    exists to ask about.

    The pass costs no API calls and no queries: the snapshot fan-out already fetched bars
    for every Stage-1 ticker (`api_calls_used` = `stage_1` + 1 on every session) and
    `load_profiles` already bulk-loads the whole Stage-1 profile map (`with_profile` =
    `stage_1`). What is left is arithmetic over data already in memory.

    **It appends no rejections and no survivors, by construction.** The candidate set is
    decided entirely by the loop above, which runs first and which this does not touch —
    that is why full evaluation cannot change what the user is shown, and it is a property
    of the shape rather than of the tests. The tests pin it anyway.

    Selection is `gap_pct is not None and rvol_pct is None`: the state already on the
    candidate says "gap was computed, RVOL was not", so no separate bookkeeping of the
    rejected set exists to fall out of step with the loop.
    """
    for candidate in candidates:
        if candidate.gap_pct is None or candidate.rvol_pct is not None:
            continue
        snapshot = snapshots.get(candidate.ticker)
        if snapshot is None:  # pragma: no cover - a gap implies a snapshot
            continue
        try:
            _assign_rvol(
                candidate, snapshot, profiles.get(candidate.ticker), rvol_calculator, as_of
            )
        except (InsufficientRvolData, FeatureRequiresIntraday):
            # Leave it NULL and move on. This ticker is already rejected, so there is no
            # decision to protect — and failing a whole scan because a ticker nobody will
            # be alerted about could not be measured would be absurd. NULL means "not
            # evaluated", which is precisely what happened; see `sweep_limitations()`.
            continue


# --------------------------------------------------------------------------- Stage 3


def stage_3_room_to_run(
    candidates: list[Candidate],
    profile: ThresholdProfile,
    also_evaluate: list[Candidate] | None = None,
) -> StageOutcome:
    """Room to run: is there enough space to the next resistance for a 5% move?

    `nearest_resistance` is the LOWEST of {high_yesterday, high_20d, sma_50, sma_200}
    that sits ABOVE the current price — the first ceiling the move would hit. A ticker
    already above all four has no measurable headroom from these levels and is rejected
    rather than assigned an unbounded upside.

    `also_evaluate` (Follow-up D) is the full Stage-1 set. Tickers in it that Stage 2
    rejected get their headroom computed but not judged: no rejection, no survivor, no
    risk filter. Pure arithmetic over reference data already loaded at Stage 1.
    """
    outcome = StageOutcome()

    for candidate in candidates:
        price = candidate.price_premarket_current
        if not price:
            outcome.rejections.append(
                Rejection(candidate.ticker, STAGE_3, "no current price", "cannot compute upside")
            )
            continue

        # Null upside after this means "above every known level", which is the one case
        # the spec asks us to reject rather than value. Sharing the rule with
        # `_assign_headroom` is deliberate: two copies of "lowest level above the price"
        # would eventually disagree, and Phase 5 would read the difference as real.
        _assign_headroom(candidate)
        if candidate.upside_pct is None:
            outcome.rejections.append(
                Rejection(
                    candidate.ticker,
                    STAGE_3,
                    "no resistance above price",
                    f"price {price:.2f} is above every known level "
                    f"({_format_levels(candidate.resistance_levels())}); headroom unmeasurable",
                )
            )
            continue

        # Inclusive, per the spec: 5.5 = 5% target + 0.5% slippage/fee buffer.
        if candidate.upside_pct < profile.upside_min:
            outcome.rejections.append(
                Rejection(
                    candidate.ticker,
                    STAGE_3,
                    "insufficient upside",
                    f"upside {candidate.upside_pct:.2f}% < {profile.upside_min}% "
                    f"(nearest resistance {candidate.resistance_source} at "
                    f"{candidate.nearest_resistance:.2f})",
                )
            )
            continue

        outcome.survivors.append(candidate)

    if also_evaluate:
        decided = {c.ticker for c in candidates}
        for candidate in also_evaluate:
            if candidate.ticker in decided:
                continue
            _assign_headroom(candidate)

    return outcome


def _assign_headroom(candidate: Candidate) -> None:
    """Write `nearest_resistance` and `upside_pct`, judging nothing.

    Shares the "lowest level above the price" rule with the decision loop above. A ticker
    above all four levels keeps both fields NULL — the same state the loop leaves behind
    when it rejects for unmeasurable headroom, and the state `docs/CLAUDE.md` 4.3 says the
    schema must tolerate.
    """
    price = candidate.price_premarket_current
    if not price or candidate.upside_pct is not None:
        return

    above = {name: level for name, level in candidate.resistance_levels().items() if level > price}
    if not above:
        return

    source = min(above, key=lambda name: above[name])
    candidate.nearest_resistance = above[source]
    candidate.resistance_source = source
    candidate.upside_pct = at_precision((candidate.nearest_resistance - price) / price * 100)


def _format_levels(levels: dict[str, float]) -> str:
    return ", ".join(f"{name}={value:.2f}" for name, value in sorted(levels.items()))
