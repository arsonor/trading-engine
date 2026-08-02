"""Scanner orchestration and `scan_runs` observability.

The single most important property here is that **a failed scan never looks like a quiet
market**. Zero candidates is a legitimate, common outcome; a crashed scan is an outage.
If both render as "no alerts today", the user stops trusting the tool at exactly the
moment it breaks. So every run lands in one of four explicit states:

| Status      | Meaning                                                      |
|-------------|--------------------------------------------------------------|
| `completed` | Ran to the end. `stage_counts_json` says how many survived.   |
| `failed`    | Something broke. `error` is populated; counts are partial.    |
| `skipped`   | Outside the 04:00–09:25 ET window; no work attempted.         |
| `running`   | In flight, or the process died before finishing.             |

A `running` row that never advanced is itself the signal that a scan died mid-flight,
which is why the row is written *before* the work starts rather than after.

Stage 3 note: the spec designates the 09:25 pass as the final confirmation run that
applies Stage 3 and pushes the definitive set. Stage 3 is nonetheless evaluated on every
run, because it is pure arithmetic over reference data already in memory and the upside
figure is useful on the dashboard well before 09:25. `is_final_pass` records which run
is the authoritative one; Phase 3 decides what to persist and push from that.
"""

import logging
import time as time_module
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.scan_run import ScanRun, ScanRunStatus
from app.services.scanner.candidate import (
    STAGE_1,
    STAGE_2,
    STAGE_3,
    STAGE_RISK,
    Candidate,
    Rejection,
)
from app.services.scanner.clock import (
    Clock,
    SystemClock,
    describe,
    is_final_pass,
    is_within_scan_window,
)
from app.services.scanner.profiles import ThresholdProfile, get_profile
from app.services.scanner.risk import (
    MarketTape,
    MarketTapeProvider,
    NeutralMarketTape,
    apply_risk_filters,
)
from app.services.scanner.rvol import RvolCalculator, get_rvol_calculator
from app.services.scanner.snapshot import SnapshotProvider
from app.services.scanner.stages import (
    stage_1_liquidity,
    stage_1_universe_size,
    stage_2_momentum,
    stage_3_room_to_run,
)

logger = logging.getLogger(__name__)


@dataclass
class StageCounts:
    """Survivor counts at each step. The shape written to `scan_runs`."""

    universe: int = 0
    stage_1: int = 0
    stage_2: int = 0
    stage_3: int = 0
    risk_passed: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "universe": self.universe,
            STAGE_1: self.stage_1,
            STAGE_2: self.stage_2,
            STAGE_3: self.stage_3,
            STAGE_RISK: self.risk_passed,
        }


@dataclass
class ScanResult:
    """Everything one scan produced, for the CLI, tests and (Phase 3) the API."""

    profile: ThresholdProfile
    as_of_et: datetime
    status: str = ScanRunStatus.RUNNING
    scan_run_id: int | None = None
    is_final_pass: bool = False
    counts: StageCounts = field(default_factory=StageCounts)
    candidates: list[Candidate] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    tape: MarketTape | None = None
    api_calls_used: int = 0
    duration_s: float = 0.0
    error: str | None = None
    dry_run: bool = False
    # Set when the funnel's shape indicates a misconfiguration rather than a quiet
    # market. Callers must show this INSTEAD of the quiet-market message.
    misconfiguration: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == ScanRunStatus.COMPLETED

    @property
    def is_quiet_market(self) -> bool:
        """Completed successfully and found nothing — NOT the same as a failure.

        False when a misconfiguration was detected: an empty result caused by broken
        thresholds is not evidence about the market.
        """
        return self.succeeded and not self.candidates and self.misconfiguration is None

    def rejections_at(self, stage: str) -> list[Rejection]:
        return [r for r in self.rejections if r.stage == stage]

    def summary(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "profile": self.profile.name,
            "is_demo": self.profile.is_demo,
            "as_of_et": self.as_of_et.isoformat(),
            "is_final_pass": self.is_final_pass,
            "counts": self.counts.as_dict(),
            "candidates": [c.ticker for c in self.candidates],
            "error": self.error,
            "misconfiguration": self.misconfiguration,
        }


class Scanner:
    """Runs the three-stage pipeline for one moment in time."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        snapshot_provider: SnapshotProvider | None = None,
        profile: ThresholdProfile | None = None,
        clock: Clock | None = None,
        rvol_calculator: RvolCalculator | None = None,
        tape_provider: MarketTapeProvider | None = None,
    ) -> None:
        if session_factory is None:
            from app.core.database import async_session_maker

            session_factory = async_session_maker
        self._session_factory = session_factory
        self._snapshots = snapshot_provider
        self._profile = profile or get_profile()
        self._clock = clock or SystemClock()
        self._rvol = rvol_calculator or get_rvol_calculator()
        self._tape = tape_provider or NeutralMarketTape()

    @property
    def profile(self) -> ThresholdProfile:
        return self._profile

    async def run(
        self,
        *,
        tickers: list[str] | None = None,
        dry_run: bool = False,
        ignore_window: bool = False,
    ) -> ScanResult:
        """Execute one scan. Expected failures are recorded, not raised."""
        started = time_module.monotonic()
        as_of = self._clock.now_et()
        result = ScanResult(
            profile=self._profile,
            as_of_et=as_of,
            is_final_pass=is_final_pass(as_of),
            dry_run=dry_run,
        )

        if self._profile.is_demo:
            logger.warning("DEMO PROFILE ACTIVE — %s", self._profile.describe())

        if not ignore_window and not is_within_scan_window(as_of):
            result.status = ScanRunStatus.SKIPPED
            result.error = (
                f"{describe(as_of)} is outside the 04:00-09:25 ET scan window; no work done."
            )
            logger.info("Scan skipped: %s", result.error)
            result.duration_s = time_module.monotonic() - started
            await self._record(result)
            return result

        if not dry_run:
            result.scan_run_id = await self._open_run(result)

        try:
            await self._execute(result, tickers)
            result.status = ScanRunStatus.COMPLETED
        except Exception as exc:  # noqa: BLE001 - the run must record why it died
            result.status = ScanRunStatus.FAILED
            result.error = f"{type(exc).__name__}: {exc}"
            logger.exception("Scan failed at %s", describe(as_of))

        result.duration_s = time_module.monotonic() - started
        await self._record(result)
        self._log_outcome(result)
        return result

    async def _execute(self, result: ScanResult, tickers: list[str] | None) -> None:
        if self._snapshots is None:
            raise ValueError(
                "Scanner has no snapshot provider. V1 has no live pre-market data — "
                "pass FixtureSnapshotProvider (CLI: --fixture)."
            )

        async with self._session_factory() as session:
            result.counts.universe = await stage_1_universe_size(session, tickers)
            stage1 = await stage_1_liquidity(session, self._profile, tickers)

        result.counts.stage_1 = len(stage1)
        # Stage 1 is a SQL filter, so the rejected rows are never materialised; the count
        # difference is the audit trail.
        logger.info(
            "Stage 1: %s/%s tickers passed (float < %s, avg vol > %s)",
            len(stage1),
            result.counts.universe,
            f"{self._profile.float_max:,}",
            f"{self._profile.avg_volume_min:,.0f}",
        )

        # The demo profile is DESIGNED so the free-tier universe clears Stage 1 — that is
        # its entire purpose. Zero survivors out of a non-empty universe therefore means
        # the thresholds are wrong (most often a stored override reverting the loosened
        # float cap), not that the market is quiet. Saying "no candidates" here would
        # send the operator to look at the market instead of at their settings.
        if self._profile.is_demo and result.counts.universe and not result.counts.stage_1:
            result.misconfiguration = (
                f"DEMO profile passed 0 of {result.counts.universe} tickers at Stage 1. "
                f"Demo exists so the free-tier universe DOES pass, so this is almost "
                f"certainly a misconfiguration rather than a quiet market. "
                f"Effective thresholds: {self._profile.threshold_summary()}. "
                f"Check stored overrides with `GET /api/v1/scanner/settings` — a value "
                f"saved for this profile can revert the loosened float cap."
            )
            logger.warning(result.misconfiguration)

        snapshots = await self._snapshots.get_snapshots(stage1, result.as_of_et)

        stage2 = stage_2_momentum(stage1, snapshots, self._profile, self._rvol, result.as_of_et)
        result.counts.stage_2 = len(stage2.survivors)
        result.rejections.extend(stage2.rejections)

        stage3 = stage_3_room_to_run(stage2.survivors, self._profile)
        result.counts.stage_3 = len(stage3.survivors)
        result.rejections.extend(stage3.rejections)

        result.tape = await self._tape.get_tape(result.as_of_et)
        risk = apply_risk_filters(stage3.survivors, self._profile, result.tape)
        result.counts.risk_passed = len(risk.survivors)
        result.rejections.extend(risk.rejections)

        result.candidates = sorted(
            risk.survivors, key=lambda c: (c.upside_pct or 0), reverse=True
        )

    # ------------------------------------------------------------------ persistence

    async def _open_run(self, result: ScanResult) -> int:
        """Write the `running` row before any work, so a crash leaves a trace."""
        async with self._session_factory() as session:
            run = ScanRun(
                started_at=datetime.utcnow(),
                status=ScanRunStatus.RUNNING,
                profile=self._profile.name,
                stage_counts_json={
                    "as_of_et": result.as_of_et.isoformat(),
                    "is_final_pass": result.is_final_pass,
                    "profile": self._profile.as_dict(),
                },
            )
            session.add(run)
            await session.commit()
            return run.id

    async def _record(self, result: ScanResult) -> None:
        """Close out the `scan_runs` row with counts, status and any error.

        Dry runs and window-skipped runs have no row: the cron fires generously in UTC,
        so recording every out-of-window wake-up would bury the real scans in noise.
        """
        if result.dry_run or result.scan_run_id is None:
            return

        async with self._session_factory() as session:
            run = await session.get(ScanRun, result.scan_run_id)
            if run is None:  # pragma: no cover - only if the row was deleted mid-run
                return
            run.finished_at = datetime.utcnow()
            run.status = result.status
            run.error = result.error
            run.api_calls_used = result.api_calls_used
            run.stage_counts_json = {
                "as_of_et": result.as_of_et.isoformat(),
                "is_final_pass": result.is_final_pass,
                "profile": self._profile.as_dict(),
                "counts": result.counts.as_dict(),
                "candidates": [c.ticker for c in result.candidates],
                "rejections": [
                    {"ticker": r.ticker, "stage": r.stage, "reason": r.reason}
                    for r in result.rejections
                ],
                "misconfiguration": result.misconfiguration,
                "snapshot_source": getattr(self._snapshots, "source", None),
                "rvol_mode": self._rvol.mode,
                "duration_s": round(result.duration_s, 3),
            }
            await session.commit()

    def _log_outcome(self, result: ScanResult) -> None:
        if result.status == ScanRunStatus.FAILED:
            logger.error(
                "SCAN FAILED at %s (profile=%s): %s",
                describe(result.as_of_et),
                self._profile.name,
                result.error,
            )
            return

        if result.misconfiguration:
            logger.warning(
                "Scan completed at %s (profile=%s) with 0 candidates, but the funnel "
                "indicates a MISCONFIGURATION, not a quiet market.",
                describe(result.as_of_et),
                self._profile.name,
            )
            return

        if result.is_quiet_market:
            logger.info(
                "Scan completed at %s (profile=%s): 0 candidates. "
                "This is a successful scan of a quiet market, not a failure.",
                describe(result.as_of_et),
                self._profile.name,
            )
            return

        logger.info(
            "Scan completed at %s (profile=%s): %s candidate(s) — %s",
            describe(result.as_of_et),
            self._profile.name,
            len(result.candidates),
            ", ".join(c.ticker for c in result.candidates),
        )
