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
from dataclasses import dataclass, field, replace
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
from app.services.scanner.integrity import (
    IntegrityFinding,
    VolumeMonotonicityGuard,
    check_price_regime_break,
    check_volume_plausibility,
)
from app.services.scanner.profile_store import load_profiles
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

# What a run is allowed to write. Three states, because two of them were conflated once
# already and the observation window produced nothing for it.
#
#   live        scan_runs written, alerts persisted and broadcast
#   observation scan_runs written, NO alerts — the two-stage go-live's first stage
#   dry_run     nothing written at all — local testing
#
# `--dry-run` has meant "touch nothing" since Phase 2. Phase 4C reused it for observation
# without checking, so the cron ran a full live scan every five minutes and discarded the
# result: `scan_runs` gained no rows and there was nothing to observe. The modes are named
# and recorded on the row now so that a run which produced no alerts BECAUSE IT WAS NOT
# ALLOWED TO is distinguishable from one that found nothing — the same distinction the
# design already draws between a failed scan and a quiet market.
MODE_LIVE = "live"
MODE_OBSERVATION = "observation"
MODE_DRY_RUN = "dry_run"


def resolve_mode(dry_run: bool, no_alerts: bool) -> str:
    """`--dry-run` wins: it is the stricter of the two."""
    if dry_run:
        return MODE_DRY_RUN
    return MODE_OBSERVATION if no_alerts else MODE_LIVE


def describe_mode(mode: str) -> str:
    """One line stating exactly what will and will not be written.

    The Phase 4C bug was caught from a single log line, which is the quality worth
    preserving: each mode says what it does, not what it is called.
    """
    return {
        MODE_LIVE: "live — scan_runs AND alerts will be written and broadcast",
        MODE_OBSERVATION: (
            "observation (--no-alerts) — scan_runs WILL be written; alerts will NOT be"
        ),
        MODE_DRY_RUN: "dry run (--dry-run) — NOTHING will be written",
    }.get(mode, mode)


@dataclass
class StageCounts:
    """Survivor counts at each step. The shape written to `scan_runs`."""

    universe: int = 0
    stage_1: int = 0
    stage_2: int = 0
    stage_3: int = 0
    risk_passed: int = 0
    # How many Stage-1 candidates had a volume profile. The rest fall back to simple
    # RVOL, flagged — a low number here explains a morning full of approximate badges.
    with_profile: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "universe": self.universe,
            "with_profile": self.with_profile,
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
    # Bytes this pass pulled from FMP. On Premium bandwidth is the binding constraint,
    # and the per-pass figure is the one the tiered-cadence decision turns on: the
    # fan-out returns every 5-minute bar since 04:00, so a pass at 04:05 and a pass at
    # 09:25 are not the same size, and pass counts alone overstate what thinning saves.
    bytes_used: int = 0
    duration_s: float = 0.0
    error: str | None = None
    dry_run: bool = False
    # What this run was permitted to write. See MODE_* above.
    mode: str = MODE_LIVE
    # Set when the funnel's shape indicates a misconfiguration rather than a quiet
    # market. Callers must show this INSTEAD of the quiet-market message.
    misconfiguration: str | None = None
    # Live-provider outcomes. A thin morning and a morning where the fan-out half failed
    # look identical from the candidate count alone; these separate them.
    snapshot_failures: dict[str, str] = field(default_factory=dict)
    not_trading: list[str] = field(default_factory=list)
    # Data-integrity guard hits, recorded rather than buried in logs.
    integrity_warnings: list[str] = field(default_factory=list)

    @property
    def data_quality_rejections(self) -> list[Rejection]:
        """Rejections caused by unusable reference data, not by the market.

        Kept distinct because they mean something different to the operator: an ordinary
        gap rejection says the stock did not qualify, while these say the scanner could
        not trust its own inputs for that ticker.
        """
        from app.services.scanner.risk import DATA_QUALITY_REASONS

        return [r for r in self.rejections if r.reason in DATA_QUALITY_REASONS]

    @property
    def data_quality_suppressed(self) -> int:
        return len(self.data_quality_rejections)

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
        # High-water marks live on the Scanner so a long-lived process can compare
        # passes; a one-shot cron simply has nothing to compare against.
        self._volume_guard = VolumeMonotonicityGuard()

    @property
    def profile(self) -> ThresholdProfile:
        return self._profile

    async def run(
        self,
        *,
        tickers: list[str] | None = None,
        dry_run: bool = False,
        no_alerts: bool = False,
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
            mode=resolve_mode(dry_run, no_alerts),
        )

        if self._profile.is_demo:
            logger.warning("DEMO PROFILE ACTIVE — %s", self._profile.describe())

        # The row opens BEFORE the window gate, not after it. A gate-skipped wake-up is an
        # audit event: it is the only durable evidence that the cron fired at all. Without
        # it, "the cron fired and correctly skipped" and "the cron never fired" are the
        # same empty query result, and only Render's logs — which expire — can tell them
        # apart. That is exactly the question the 09:25 investigation had to answer.
        if not dry_run:
            result.scan_run_id = await self._open_run(result)

        if not ignore_window and not is_within_scan_window(as_of):
            result.status = ScanRunStatus.SKIPPED
            result.error = (
                f"{describe(as_of)} is outside the 04:00-09:25 ET scan window; no work done."
            )
            logger.info("Scan skipped: %s", result.error)
            result.duration_s = time_module.monotonic() - started
            await self._record(result)
            return result

        # Bracket the work with the budget counters, so this pass's own cost is known.
        # A failed pass still spent whatever it spent before it died, which is why the
        # closing read happens after the except rather than inside the try.
        spend_before = await self._budget_counters()

        try:
            await self._execute(result, tickers)
            result.status = ScanRunStatus.COMPLETED
        except Exception as exc:  # noqa: BLE001 - the run must record why it died
            result.status = ScanRunStatus.FAILED
            result.error = f"{type(exc).__name__}: {exc}"
            logger.exception("Scan failed at %s", describe(as_of))

        self._apply_spend(result, spend_before, await self._budget_counters())
        result.duration_s = time_module.monotonic() - started
        await self._record(result)
        self._log_outcome(result)
        return result

    async def _budget_counters(self) -> tuple[int, int] | None:
        """Today's (calls, bytes) totals, or None if they cannot be read.

        Read from the shared `api_budget` counters rather than from the FMP client, so
        the scanner does not have to reach inside whichever provider it was handed — a
        fixture run simply reports a delta of zero.

        Best-effort by design: instrumentation must never be the reason a pass fails.
        """
        try:
            from app.services.fmp.budget import DailyBudgetGuard

            guard = DailyBudgetGuard(self._session_factory)
            return await guard.calls_used_today(), await guard.bytes_used_today()
        except Exception:  # noqa: BLE001 - see docstring
            logger.debug("Could not read the FMP budget counters for this pass", exc_info=True)
            return None

    @staticmethod
    def _apply_spend(
        result: ScanResult, before: tuple[int, int] | None, after: tuple[int, int] | None
    ) -> None:
        """Record what this pass cost, as a delta over the daily counters.

        The delta is honest only because nothing else touches FMP during the scan window:
        the nightly refresh runs at night, and passes do not overlap. The counters are
        keyed on the UTC day, and 04:00-09:25 ET is 08:00-13:25 UTC, so a pass can never
        straddle the rollover that would make a delta negative.

        `api_calls_used` has been on `scan_runs` since the v2 schema and was written as 0
        by every run ever recorded, because nothing populated it. Both figures matter for
        the tiered-cadence decision: bytes are the binding constraint on Premium, and the
        per-pass byte curve is what says whether thinning early passes saves what the
        pass count suggests it should.
        """
        if before is None or after is None:
            return
        result.api_calls_used = max(after[0] - before[0], 0)
        result.bytes_used = max(after[1] - before[1], 0)

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

        # Live providers report what they could not reach. Recorded on the run so a thin
        # morning can be told apart from a morning where a third of the fan-out failed —
        # both look like "few candidates" from the outside.
        result.snapshot_failures = dict(getattr(self._snapshots, "failures", {}) or {})
        result.not_trading = list(getattr(self._snapshots, "not_trading", []) or [])

        # RVOL's denominator. Loaded in one query for the whole Stage-1 set; a per-ticker
        # round-trip would not fit the cadence at ~694 candidates.
        async with self._session_factory() as session:
            vol_profiles = await load_profiles(session, [c.ticker for c in stage1])
        result.counts.with_profile = len(vol_profiles)

        # Guards run BEFORE Stage 2 so a corrected volume is what the stage decides on,
        # and so a flagged ticker is flagged even if it is later rejected for gap.
        snapshots, findings = self._apply_integrity_guards(stage1, snapshots)
        result.integrity_warnings = [str(f) for f in findings]

        stage2 = stage_2_momentum(
            stage1, snapshots, self._profile, self._rvol, result.as_of_et,
            profiles=vol_profiles,
        )
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

    def _apply_integrity_guards(
        self, candidates: list[Candidate], snapshots: dict[str, Any]
    ) -> tuple[dict[str, Any], list[IntegrityFinding]]:
        """Observe and record. These never reject a candidate — see integrity.py.

        The one correction applied is the monotonicity high-water mark: a volume that went
        DOWN within a session is a data fault, and acting on the lower number would
        understate RVOL for the rest of the morning.
        """
        findings: list[IntegrityFinding] = []
        corrected = dict(snapshots)

        for candidate in candidates:
            snapshot = corrected.get(candidate.ticker)
            if snapshot is None:
                continue

            kept = self._volume_guard.check(
                candidate.ticker, snapshot.volume_premarket_accumulated
            )
            if kept != snapshot.volume_premarket_accumulated:
                corrected[candidate.ticker] = replace(
                    snapshot, volume_premarket_accumulated=kept
                )

            for finding in (
                check_volume_plausibility(candidate, kept),
                check_price_regime_break(candidate),
            ):
                if finding is not None:
                    findings.append(finding)
                    logger.warning("INTEGRITY %s", finding)

        findings.extend(self._volume_guard.findings[len(findings):])
        return corrected, findings

    # ------------------------------------------------------------------ persistence

    async def _open_run(self, result: ScanResult) -> int:
        """Write the `running` row before any work, so a crash leaves a trace."""
        async with self._session_factory() as session:
            run = ScanRun(
                started_at=datetime.utcnow(),
                status=ScanRunStatus.RUNNING,
                profile=self._profile.name,
                # Written up front, not only on completion: a run that dies mid-flight
                # leaves a `running` row, and that row still has to say what it was doing.
                mode=result.mode,
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

        Only a dry run has no row. A window-skipped wake-up does get one — see `run()`.
        The counts on it are all zero, which is truthful: no work was attempted.
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
            run.mode = result.mode
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
                # In the JSON blob rather than a new column: this is observability that
                # has to earn a schema change first, and the cadence question it exists
                # to answer needs a handful of sessions, not a permanent index.
                "bytes_used": result.bytes_used,
                # Live-path observability. Without these a morning where 200 of 694
                # tickers failed to fetch is indistinguishable from a genuinely quiet one —
                # both just report few candidates.
                "snapshot_failures": result.snapshot_failures,
                "not_trading_count": len(result.not_trading),
                "integrity_warnings": result.integrity_warnings,
                # Suppressed candidates are counted separately: "3 suppressed for
                # implausible reference data" is information, a silent drop is not.
                "data_quality_suppressed": result.data_quality_suppressed,
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
