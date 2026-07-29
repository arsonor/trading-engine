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
    is_final_pass: bool = False
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
            is_demo=bool(run.profile and run.profile != PRODUCTION_PROFILE),
            started_at=run.started_at,
            finished_at=run.finished_at,
            api_calls_used=run.api_calls_used,
            error=run.error,
            stage_counts=run.stage_counts_json,
        )


class ScannerStatus(BaseModel):
    """Everything the scan-status panel needs to distinguish quiet from broken."""

    last_run: Optional[ScanRunOut] = None
    last_successful_run: Optional[ScanRunOut] = None
    is_healthy: bool = Field(
        True, description="False when the most recent run failed, or none has ever run."
    )
    # The distinction Phase 2 exists to preserve, carried into the UI contract.
    state: str = Field(
        "unknown",
        description=(
            "never_run | ok_with_candidates | ok_no_candidates | failed | stale. "
            "'ok_no_candidates' is a healthy quiet market; 'failed' is an outage."
        ),
    )
    detail: str = ""
    session_date: Optional[date] = None
    alert_count: int = 0
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
