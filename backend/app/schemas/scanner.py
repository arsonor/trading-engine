"""Pydantic schemas for the v2 scanner API.

Two things in here are load-bearing beyond ordinary serialisation:

1. **`upside_pct` and `nearest_resistance` are `Optional`.** Today Stage 3 never emits a
   null (it rejects tickers with no overhead resistance), but that is a deferred strategy
   decision — see `docs/CLAUDE.md` 4.3 "Breakout convention". Declaring them required
   would bake the current behaviour into the published contract and into every generated
   TypeScript type, turning a one-branch reversal into a breaking API change.

2. **Honesty flags travel with the data.** `is_demo`, `is_provisional` and
   `rvol_is_approximate` are part of the payload, not presentation. A client that renders
   the number without them is rendering a lie, and the schema should make that hard.

Naming: storage and API agree on `ticker`. The `symbol` -> `ticker` mapping layer that
existed while the v1 tables still used `symbol` was removed in Phase 3.5.
"""

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

PRODUCTION_PROFILE = "production"


class ScoreFactorOut(BaseModel):
    """One component of a confidence score."""

    name: str
    raw_value: Optional[float] = None
    normalized: float
    weight: float
    contribution: float
    detail: str
    is_fallback: bool = False


class ScoreBreakdownOut(BaseModel):
    """The full justification for a confidence score."""

    score: float
    is_provisional: bool = True
    profile: str = ""
    uses_fallback: bool = False
    factors: list[ScoreFactorOut] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ScannerAlert(BaseModel):
    """A scanner alert — the `docs/CLAUDE.md` 4.4 output contract."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    session_date: Optional[date] = None
    scan_timestamp: Optional[datetime] = None
    scan_run_id: Optional[int] = None

    gap_pct: Optional[float] = None
    rvol_pct: Optional[float] = None
    rvol_mode: Optional[str] = None
    rvol_is_approximate: bool = False
    # Decision-time provenance (Phase 4C). Exposed rather than kept internal because it is
    # what lets a reader tell a bad call from data that was revised afterwards — 4A
    # measured 49.4% of pre-market bars revised upward within ~7 minutes of closing.
    bars_settled_through: Optional[datetime] = Field(
        None,
        description="Effective data cut-off: the newest bar old enough to be trusted. "
                    "Earlier than scan_timestamp by the settling window.",
    )
    provisional_bars_excluded: Optional[int] = Field(
        None, description="Bars dropped for being too fresh to have settled."
    )
    profile_sessions_sampled: Optional[int] = Field(
        None,
        description="Sessions averaged into the RVOL denominator. A low number means a "
                    "noisier normalization; null means no profile and simple RVOL.",
    )
    catalyst: Optional[str] = Field(
        None, description="News/earnings tag. Always null in V1 — catalyst tagging is Phase 4."
    )

    confidence_score: Optional[float] = None
    score_breakdown: Optional[ScoreBreakdownOut] = None

    suggested_entry_window: Optional[str] = None
    entry_reference_price: Optional[float] = None
    nearest_resistance: Optional[float] = Field(
        None,
        description=(
            "Lowest resistance level above the current price. NULL when the ticker "
            "trades above every known level — headroom is then unmeasured, not zero."
        ),
    )
    resistance_source: Optional[str] = None
    upside_pct: Optional[float] = Field(
        None, description="Percent to nearest resistance. NULL when there is none above price."
    )

    profile: Optional[str] = None
    is_demo: bool = False
    # "Confirmed" versus "faded", and the reason the dashboard can separate the two lists
    # without parsing the entry-window string. The row is updated in place on every pass,
    # so this reflects the LAST pass that saw the ticker qualify: true means it was still
    # a candidate at 09:25, false means it stopped being one somewhere before then.
    is_final_pass: bool = Field(
        False, description="True when the 09:25 ET confirmation pass last updated this alert."
    )
    is_read: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_model(cls, alert) -> "ScannerAlert":
        """Build the contract from an ORM row.

        Still explicit rather than `model_validate`: `score_breakdown` is a nested model
        parsed from a JSON column and `is_demo` is a derived property, neither of which
        `from_attributes` handles for free.
        """
        breakdown = alert.score_breakdown_json
        return cls(
            id=alert.id,
            ticker=alert.ticker,
            session_date=alert.session_date,
            scan_timestamp=alert.scan_timestamp,
            scan_run_id=alert.scan_run_id,
            gap_pct=alert.gap_pct,
            rvol_pct=alert.rvol_pct,
            rvol_mode=alert.rvol_mode,
            rvol_is_approximate=alert.rvol_is_approximate,
            bars_settled_through=alert.bars_settled_through,
            provisional_bars_excluded=alert.provisional_bars_excluded,
            profile_sessions_sampled=alert.profile_sessions_sampled,
            catalyst=alert.catalyst,
            confidence_score=alert.confidence_score,
            score_breakdown=ScoreBreakdownOut(**breakdown) if breakdown else None,
            suggested_entry_window=alert.suggested_entry_window,
            entry_reference_price=alert.entry_reference_price,
            nearest_resistance=alert.nearest_resistance,
            resistance_source=alert.resistance_source,
            upside_pct=alert.upside_pct,
            profile=alert.profile,
            is_demo=alert.is_demo,
            is_final_pass=alert.is_final_pass,
            is_read=alert.is_read,
            created_at=alert.created_at,
            updated_at=alert.updated_at,
        )


class ScannerAlertListResponse(BaseModel):
    """Session alerts plus the context needed to frame them honestly."""

    items: list[ScannerAlert]
    total: int
    session_date: Optional[date] = None
    has_demo_alerts: bool = Field(
        False, description="True if any alert came from a loosened demo profile."
    )


class ScanRunOut(BaseModel):
    """One scan execution, for the scan-status panel."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str = Field(
        ..., description="completed | failed | skipped | running. Never conflate these."
    )
    profile: Optional[str] = None
    # What the run was permitted to write: live | observation | dry_run. NULL for runs
    # recorded before the column existed.
    #
    # Surfaced because the Scans panel exists to answer "is the scanner working?", and
    # during the observation stage a perfectly healthy run produces zero alerts by design.
    # Without the mode, that is indistinguishable from a quiet market — the same conflation
    # the failure taxonomy already works to avoid.
    mode: Optional[str] = None
    is_demo: bool = False
    started_at: datetime
    finished_at: Optional[datetime] = None
    api_calls_used: int = 0
    error: Optional[str] = None
    stage_counts: Optional[dict[str, Any]] = None

    @classmethod
    def from_model(cls, run) -> "ScanRunOut":
        return cls(
            id=run.id,
            status=run.status,
            profile=run.profile,
            mode=run.mode,
            is_demo=bool(run.profile and run.profile != PRODUCTION_PROFILE),
            started_at=run.started_at,
            finished_at=run.finished_at,
            api_calls_used=run.api_calls_used,
            error=run.error,
            stage_counts=run.stage_counts_json,
        )


class ScannerStatus(BaseModel):
    """Everything the scan-status panel needs to distinguish quiet from broken."""

    # The last run that ATTEMPTED work. Out-of-window wake-ups (`skipped`) are excluded:
    # they carry no counts and there are ~18 of them after each session, so treating the
    # newest row as "the last scan" would hide every morning's result from 09:30 ET
    # onwards. They remain visible in `recent_runs` — that is where "did the cron fire?"
    # is answered.
    last_run: Optional[ScanRunOut] = None
    last_successful_run: Optional[ScanRunOut] = None
    is_healthy: bool = Field(
        True, description="False when the most recent run failed, or none has ever run."
    )
    # The distinction Phase 2 exists to preserve, carried into the UI contract.
    state: str = Field(
        "unknown",
        description=(
            "never_run | ok_with_candidates | ok_no_candidates | failed | skipped. "
            "'ok_no_candidates' is a healthy quiet market; 'failed' is an outage; "
            "'skipped' means the cron is alive but has never yet woken inside the window."
        ),
    )
    detail: str = ""
    session_date: Optional[date] = None
    # A session total is NOT a scan result. Alerts dedup per (ticker, session) across the
    # morning's ~66 passes, so `alert_count` is "qualified at some point since 04:00" while
    # `confirmed_count` is "still qualified at 09:25". The panel reported the first under a
    # per-scan label and was contradicted by its own funnel; both travel separately now.
    alert_count: int = Field(
        0, description="Distinct tickers that qualified at ANY point in the session."
    )
    confirmed_count: int = Field(
        0,
        description="How many of them still qualified at the authoritative 09:25 ET pass. "
                    "The remainder faded. Meaningless until final_pass_complete is true.",
    )
    final_pass_complete: bool = Field(
        False,
        description="Whether the 09:25 ET confirmation pass has run for this session. "
                    "False means nothing is confirmed YET — which is not the same "
                    "statement as a confirmed count of zero.",
    )
    # When the cron last woke up AT ALL, heartbeats included. Distinct from `last_run`,
    # which is the last wake-up that attempted work, and the two answer different
    # questions: "is the cron alive right now?" against "what did the scanner last see?".
    # Both are needed since the cadence was tiered — 65 of a weekday's 84 wake-ups are now
    # heartbeats, so an hours-old `last_run` is normal and is not evidence of a fault.
    last_wake_up_at: Optional[datetime] = Field(
        None, description="Last cron wake-up of any kind, including skipped heartbeats."
    )
    recent_runs: list[ScanRunOut] = Field(default_factory=list)


class ThresholdSettings(BaseModel):
    """Effective thresholds, and which of them the user has pinned."""

    profile: str
    is_demo: bool = False
    float_max: int
    avg_volume_min: float
    gap_min: float
    gap_max: float
    rvol_min: float
    upside_min: float
    price_floor: float
    dollar_volume_min: float
    overrides: dict[str, Any] = Field(
        default_factory=dict, description="Keys the user pinned; the rest come from env."
    )
    description: str = ""


class ThresholdSettingsUpdate(BaseModel):
    """Threshold edits from the Settings screen. All fields optional."""

    profile: Optional[str] = None
    float_max: Optional[int] = Field(None, ge=0)
    avg_volume_min: Optional[float] = Field(None, ge=0)
    gap_min: Optional[float] = Field(None, ge=0)
    gap_max: Optional[float] = Field(None, ge=0)
    rvol_min: Optional[float] = Field(None, ge=0)
    upside_min: Optional[float] = Field(None, ge=0)
    price_floor: Optional[float] = Field(None, ge=0)
    dollar_volume_min: Optional[float] = Field(None, ge=0)

    def threshold_overrides(self) -> dict[str, Any]:
        """Only the threshold fields, excluding profile and unset values."""
        return {
            key: value
            for key, value in self.model_dump(exclude_none=True).items()
            if key != "profile"
        }
