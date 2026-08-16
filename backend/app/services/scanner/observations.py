"""Recording what the scanner saw, for Phase 6 to replay.

The rationale for the table lives in `app/models/scan_observation.py`. This module owns
two decisions: **which passes write** and **what a row says about a ticker that never
finished being evaluated**.

## Which passes write

| Pass                     | Writes                          |
|--------------------------|---------------------------------|
| the authoritative 09:25  | every Stage-1 survivor (~741)   |
| an anchor (04:15/07:00/08:30) | candidates only            |
| anything else            | nothing                         |

The full write happens at the final pass because a threshold sweep needs the **rejected**
population, not just the survivors: "would a 2.5% gap floor have caught anything?" is a
question about tickers the scanner threw away. The anchors keep the early-versus-late
question answerable at a granularity that survives a tiered cadence — and one that matches
what the data can actually support, since consecutive passes are near-duplicates.

## Short-circuit evaluation, and what NULL means

The stages stop at the first failure, so a ticker rejected on gap never has RVOL computed
and its `rvol_pct` is NULL. **NULL means "never evaluated", not zero**, and a sweep must
treat the two differently: widening the gap band surfaces tickers whose RVOL was never
measured, so their fate under the new threshold is *unknown* rather than *passing*.

`sweep_limitations()` states this in one place so an analysis cannot quietly assume
otherwise. Making it fully answerable would mean evaluating every stage for every ticker
regardless of earlier failures — no extra API calls, since the data is already in memory,
but a change to stage flow that this brief explicitly puts out of scope.
"""

import logging
from datetime import time

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.scan_observation import ScanObservation
from app.services.scanner.candidate import STAGE_RISK, Candidate, Rejection
from app.services.scanner.clock import at_minute

logger = logging.getLogger(__name__)

# Passes that record their candidates. 04:15 is the discovery pass — the first that can
# see anything, since the 04:00 bar is not settled until ~04:12 — and 07:00 and 08:30
# bracket the morning. The 09:25 pass is not listed: it writes everything, always.
DEFAULT_ANCHOR_TIMES: tuple[time, ...] = (time(4, 15), time(7, 0), time(8, 30))


def sweep_limitations() -> str:
    """What a threshold sweep over these rows can and cannot conclude."""
    return (
        "Stages short-circuit, so a ticker rejected at an earlier stage has NULL for the "
        "later stages' values. NULL means NOT EVALUATED, never zero: a sweep that widens "
        "an early threshold must report the newly-admitted tickers as unresolved rather "
        "than as passing."
    )


def should_record_all(is_final_pass: bool) -> bool:
    """The full Stage-1 population is recorded only at the authoritative pass."""
    return is_final_pass


def is_anchor_pass(as_of, anchors: tuple[time, ...] = DEFAULT_ANCHOR_TIMES) -> bool:
    """Whether this pass records its candidates.

    Compared at minute resolution through `at_minute`, for the same reason the scan window
    is: Render starts a job 10-45 s after its scheduled minute, so an anchor at 07:00 has
    to match a pass that began at 07:00:23.
    """
    return at_minute(as_of).time() in anchors


class ObservationRecorder:
    """Writes `scan_observations` rows for one pass."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        anchors: tuple[time, ...] = DEFAULT_ANCHOR_TIMES,
    ) -> None:
        if session_factory is None:
            from app.core.database import async_session_maker

            session_factory = async_session_maker
        self._session_factory = session_factory
        self._anchors = anchors

    async def record(self, result, stage_1_survivors: list[Candidate]) -> int:
        """Persist this pass's observations. Returns how many rows were written.

        Never raises. A pass that cannot record its evidence is still a pass that produced
        alerts, and failing it here would trade a live signal for a backtest row.
        """
        try:
            return await self._record(result, stage_1_survivors)
        except Exception:  # noqa: BLE001 - see docstring
            logger.exception(
                "Could not record scan observations for run %s; the scan itself is "
                "unaffected.",
                result.scan_run_id,
            )
            return 0

    async def _record(self, result, stage_1_survivors: list[Candidate]) -> int:
        if result.scan_run_id is None or result.dry_run:
            return 0
        if not result.succeeded:
            # A failed pass has a partial, untrustworthy population. Recording it would
            # put rows in the evidence table that no decision was ever made from.
            return 0

        record_all = should_record_all(result.is_final_pass)
        if not record_all and not is_anchor_pass(result.as_of_et, self._anchors):
            return 0

        candidates = {c.ticker for c in result.candidates}
        subjects = stage_1_survivors if record_all else list(result.candidates)
        if not subjects:
            return 0

        # One rejection per ticker at most: each stage only sees the previous stage's
        # survivors, so a ticker cannot be rejected twice.
        rejections: dict[str, Rejection] = {r.ticker: r for r in result.rejections}

        rows = [
            self._build(candidate, result, rejections.get(candidate.ticker), candidates)
            for candidate in subjects
        ]

        async with self._session_factory() as session:
            # A retry after a partial failure must converge, not duplicate. The unique
            # constraint is on (scan_run_id, ticker), so the run's existing rows go first.
            #
            # A Core DELETE, not `session.delete()` on loaded objects: the ORM's unit of
            # work flushes INSERTs before DELETEs, so the deletes would land after the
            # rows they are meant to make room for and the insert would violate the
            # constraint. This statement executes immediately, and it does not load 741
            # objects to throw them away.
            await session.execute(
                delete(ScanObservation).where(
                    ScanObservation.scan_run_id == result.scan_run_id
                )
            )
            session.add_all(rows)
            await session.commit()

        logger.info(
            "Recorded %s scan observation(s) for run %s (%s)",
            len(rows),
            result.scan_run_id,
            "full Stage-1 population" if record_all else "candidates only",
        )
        return len(rows)

    @staticmethod
    def _build(
        candidate: Candidate, result, rejection: Rejection | None, candidates: set[str]
    ) -> ScanObservation:
        is_candidate = candidate.ticker in candidates
        return ScanObservation(
            scan_run_id=result.scan_run_id,
            session_date=result.as_of_et.date(),
            observed_at=result.as_of_et.replace(tzinfo=None),
            is_final_pass=result.is_final_pass,
            ticker=candidate.ticker,
            # A survivor "reached" the risk filter, which is the last gate there is.
            stage_reached=rejection.stage if rejection else STAGE_RISK,
            rejection_reason=rejection.reason[:80] if rejection else None,
            rejection_detail=(rejection.detail or None) if rejection else None,
            is_candidate=is_candidate,
            price_premarket_current=candidate.price_premarket_current,
            volume_premarket_accumulated=candidate.volume_premarket_accumulated,
            gap_pct=candidate.gap_pct,
            rvol_pct=candidate.rvol_pct,
            rvol_mode=candidate.rvol_mode,
            rvol_is_approximate=candidate.rvol_is_approximate,
            bars_settled_through=(
                candidate.bars_settled_through.replace(tzinfo=None)
                if candidate.bars_settled_through
                else None
            ),
            provisional_bars_excluded=candidate.provisional_bars_excluded,
            profile_sessions_sampled=candidate.profile_sessions_sampled,
            snapshot_source=candidate.snapshot_source,
            static_float=candidate.static_float,
            volume_avg_20d=candidate.volume_avg_20d,
            price_close_yesterday=candidate.price_close_yesterday,
            high_yesterday=candidate.high_yesterday,
            high_20d=candidate.high_20d,
            sma_50=candidate.sma_50,
            sma_200=candidate.sma_200,
            nearest_resistance=candidate.nearest_resistance,
            resistance_source=candidate.resistance_source,
            upside_pct=candidate.upside_pct,
        )
