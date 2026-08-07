"""Persist and broadcast scanner alerts.

**Dedup is per ticker per session.** Scans run every 5 minutes from 04:00 to 09:25 ET, so
a ticker that qualifies all morning would otherwise generate ~66 alerts. Instead one row
per (ticker, session) is updated in place as the picture changes, and the 09:25 pass is
the authoritative one. The user sees a short list that evolves, not a feed that repeats.

The upsert is keyed on `(ticker, session_date)`, matching the unique constraint, so two
scans racing on the same ticker cannot produce duplicates.

Broadcast reuses the existing WebSocket `alerts` channel with an extended payload — the
transport is unchanged, per the phase constraints.
"""

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.alert import Alert
from app.services.scanner.candidate import Candidate
from app.services.scanner.pipeline import ScanResult
from app.services.scanner.scoring import compute_confidence, suggested_entry_window

logger = logging.getLogger(__name__)


@dataclass
class PersistReport:
    """What one persistence pass did."""

    created: list[str]
    updated: list[str]
    session_date: date | None = None
    broadcast: int = 0

    @property
    def total(self) -> int:
        return len(self.created) + len(self.updated)


class ScannerAlertService:
    """Turns a `ScanResult` into persisted, scored, broadcast alerts."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        broadcaster=None,
    ) -> None:
        if session_factory is None:
            from app.core.database import async_session_maker

            session_factory = async_session_maker
        self._session_factory = session_factory
        self._broadcaster = broadcaster

    async def persist_scan_result(
        self, result: ScanResult, broadcast: bool = True
    ) -> PersistReport:
        """Score, upsert and broadcast every candidate from a scan.

        Only successful scans persist: a failed run's partial candidate list is not a
        result, and writing it would let an outage masquerade as a thin session.
        """
        report = PersistReport(created=[], updated=[], session_date=result.as_of_et.date())

        if not result.succeeded:
            logger.info(
                "Scan did not complete (status=%s); no alerts persisted.", result.status
            )
            return report

        for candidate in result.candidates:
            payload = self._build_payload(candidate, result)
            created = await self._upsert(payload, result)
            (report.created if created else report.updated).append(candidate.ticker)

        # Broadcast on EVERY completed scan, including one that persisted nothing.
        # Gating this on `report.total` meant a successful zero-candidate scan pushed
        # nothing, so a dashboard showing "SCANNER FAILING" from an earlier run stayed
        # stuck on it until the next status poll. The failure-to-healthy transition is
        # the single most important thing to deliver promptly.
        if broadcast:
            report.broadcast = await self._broadcast(result)

        logger.info(
            "Persisted %s alert(s) for session %s: %s created, %s updated (profile=%s)",
            report.total,
            report.session_date,
            len(report.created),
            len(report.updated),
            result.profile.name,
        )
        return report

    def _build_payload(self, candidate: Candidate, result: ScanResult) -> dict:
        """Compute the score and assemble the v2 alert contract fields."""
        score = compute_confidence(candidate, result.profile, result.as_of_et)

        return {
            "ticker": candidate.ticker,
            "session_date": result.as_of_et.date(),
            "timestamp": result.as_of_et.replace(tzinfo=None),
            "scan_timestamp": result.as_of_et.replace(tzinfo=None),
            "scan_run_id": result.scan_run_id,
            "profile": result.profile.name,
            "is_final_pass": result.is_final_pass,
            "gap_pct": candidate.gap_pct,
            "rvol_pct": candidate.rvol_pct,
            "rvol_mode": candidate.rvol_mode,
            "rvol_is_approximate": candidate.rvol_is_approximate,
            # What the scanner actually saw, so V3 can distinguish a wrong call from data
            # that was revised afterwards. See docs/FMP_PREMIUM_FINDINGS.md section 3.
            "bars_settled_through": candidate.bars_settled_through.replace(tzinfo=None)
            if candidate.bars_settled_through
            else None,
            "provisional_bars_excluded": candidate.provisional_bars_excluded,
            "profile_sessions_sampled": candidate.profile_sessions_sampled,
            # Catalyst tagging is Phase 4 (needs FMP news + earnings calendar).
            "catalyst": None,
            "entry_reference_price": candidate.price_premarket_current,
            # Both nullable by design — see docs/CLAUDE.md 4.3 "Breakout convention".
            "nearest_resistance": candidate.nearest_resistance,
            "resistance_source": candidate.resistance_source,
            "upside_pct": candidate.upside_pct,
            "suggested_entry_window": suggested_entry_window(
                result.as_of_et, result.is_final_pass
            ),
            "confidence_score": score.score,
            "score_breakdown_json": score.as_dict(),
        }

    async def _upsert(self, payload: dict, result: ScanResult) -> bool:
        """Insert or update one alert. Returns True when a row was created."""
        async with self._session_factory() as session:
            existing = await session.scalar(
                select(Alert).where(
                    Alert.ticker == payload["ticker"],
                    Alert.session_date == payload["session_date"],
                )
            )

            if existing is not None:
                for key, value in payload.items():
                    setattr(existing, key, value)
                # A re-alert in the same session is worth re-surfacing.
                existing.is_read = False
                await session.commit()
                return False

            session.add(Alert(**payload))
            try:
                await session.commit()
                return True
            except IntegrityError:
                # Another scan inserted the same (ticker, session) first; fall back to
                # an update so concurrent passes converge instead of failing.
                await session.rollback()

        async with self._session_factory() as session:
            existing = await session.scalar(
                select(Alert).where(
                    Alert.ticker == payload["ticker"],
                    Alert.session_date == payload["session_date"],
                )
            )
            if existing is not None:
                for key, value in payload.items():
                    setattr(existing, key, value)
                await session.commit()
            return False

    async def session_alerts(self, session_date: date | None = None) -> list[Alert]:
        """Alerts for one session, strongest first."""
        async with self._session_factory() as session:
            stmt = select(Alert).where(Alert.session_date.isnot(None))
            if session_date is not None:
                stmt = stmt.where(Alert.session_date == session_date)
            stmt = stmt.order_by(
                Alert.session_date.desc(), Alert.confidence_score.desc().nullslast()
            )
            return list((await session.execute(stmt)).scalars().all())

    async def _broadcast(self, result: ScanResult) -> int:
        """Push the session's current alert set over the existing WebSocket channel.

        Sends the whole session set rather than just this scan's candidates, so a client
        that missed earlier pushes converges on the correct list. An empty set is still
        broadcast — it carries the scan metadata the status panel needs.
        """
        alerts = await self.session_alerts(result.as_of_et.date())

        broadcaster = self._broadcaster
        if broadcaster is None:
            from app.api.v1.websocket import get_manager

            broadcaster = get_manager()

        from app.schemas.scanner import ScannerAlert

        message = {
            "type": "scan_alerts",
            "data": {
                "session_date": result.as_of_et.date().isoformat(),
                "scan_run_id": result.scan_run_id,
                "profile": result.profile.name,
                "is_demo": result.profile.is_demo,
                "is_final_pass": result.is_final_pass,
                "scan_timestamp": result.as_of_et.isoformat(),
                "alerts": [
                    ScannerAlert.from_model(alert).model_dump(mode="json") for alert in alerts
                ],
            },
        }

        try:
            await broadcaster.broadcast_to_channel("alerts", message)
        except Exception as exc:  # noqa: BLE001 - a broadcast failure must not lose the scan
            logger.error("Failed to broadcast scan alerts: %s", exc)
            return 0

        return len(alerts)
