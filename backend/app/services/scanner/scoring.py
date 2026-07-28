"""Confidence scoring.

**Every score this module produces is PROVISIONAL.** The weights are reasoned
assumptions, not fitted parameters — nothing has been backtested, and that only becomes
possible at app V3 (Phase 6) when historical intraday data is available. The API marks
every score `is_provisional: true` and the UI must never present it as validated. A
number between 0 and 1 looks authoritative whether or not it has earned it, so the
labelling is part of the contract, not decoration.

The formula is a weighted sum of five normalised factors:

| Factor        | Weight | Rationale                                                  |
|---------------|--------|------------------------------------------------------------|
| gap position  | 0.20   | Where in the band the gap sits; near the ceiling the move is already spent |
| RVOL          | 0.30   | Volume conviction — the strongest available signal that the gap is real   |
| upside        | 0.25   | Room to the next ceiling                                    |
| liquidity     | 0.15   | Can the position actually be traded in size                 |
| data quality  | 0.10   | How much the inputs can be trusted at all                   |

Each factor reports its raw value, its normalised 0–1 score, its weight and its
contribution, so the UI can show *why* a score is what it is rather than asking the user
to trust it.

**Null `upside_pct` is a first-class case, not an edge case.** Stage 3 currently rejects
tickers trading above all four resistance levels, so in practice every alert reaching
this module has a float upside. That rejection is a deferred strategy decision (see
`docs/CLAUDE.md` 4.3 "Breakout convention") which may be reversed after live V2
experience. If scoring assumed a non-null upside, reversing it would become a
cross-cutting refactor. So the headroom factor falls back to a neutral, configurable
score and flags itself — unmeasured headroom is neither bad nor good.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime

from app.config import get_settings
from app.services.scanner.candidate import Candidate
from app.services.scanner.profiles import ThresholdProfile

logger = logging.getLogger(__name__)

FACTOR_GAP = "gap_position"
FACTOR_RVOL = "rvol"
FACTOR_UPSIDE = "upside_headroom"
FACTOR_LIQUIDITY = "liquidity"
FACTOR_DATA_QUALITY = "data_quality"


@dataclass(frozen=True)
class ScoreFactor:
    """One component of a confidence score, with its arithmetic exposed."""

    name: str
    raw_value: float | None
    normalized: float
    weight: float
    detail: str
    is_fallback: bool = False

    @property
    def contribution(self) -> float:
        return self.normalized * self.weight

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "raw_value": self.raw_value,
            "normalized": round(self.normalized, 4),
            "weight": self.weight,
            "contribution": round(self.contribution, 4),
            "detail": self.detail,
            "is_fallback": self.is_fallback,
        }


@dataclass(frozen=True)
class ConfidenceScore:
    """A score plus the full breakdown that justifies it."""

    score: float
    factors: list[ScoreFactor] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    profile: str = ""
    # Always True in V1/V2. Only Phase 6 backtesting can retire this.
    is_provisional: bool = True

    @property
    def uses_fallback(self) -> bool:
        return any(f.is_fallback for f in self.factors)

    def as_dict(self) -> dict:
        return {
            "score": round(self.score, 4),
            "is_provisional": self.is_provisional,
            "profile": self.profile,
            "uses_fallback": self.uses_fallback,
            "factors": [f.as_dict() for f in self.factors],
            "notes": self.notes,
        }


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def score_gap(candidate: Candidate, profile: ThresholdProfile, settings) -> ScoreFactor:
    """Where the gap sits in the band.

    Rises from the floor to a peak a quarter of the way in, then decays toward the
    ceiling: a gap that has already run 15% has spent most of the move it was screened
    for, while one just over the 3% floor has barely distinguished itself from noise.
    """
    weight = settings.score_weight_gap
    gap = candidate.gap_pct
    if gap is None:
        return ScoreFactor(FACTOR_GAP, None, 0.0, weight, "no gap computed", is_fallback=True)

    band = profile.gap_max - profile.gap_min
    if band <= 0:  # pragma: no cover - guarded by config validation
        return ScoreFactor(FACTOR_GAP, gap, 0.5, weight, "degenerate gap band", is_fallback=True)

    position = _clamp((gap - profile.gap_min) / band)
    peak = _clamp(settings.score_gap_peak_position, 0.01, 0.99)

    if position <= peak:
        normalized = 0.6 + 0.4 * (position / peak)
        shape = "rising toward the strongest part of the band"
    else:
        normalized = 1.0 - 0.7 * ((position - peak) / (1 - peak))
        shape = "decaying — much of the move is already spent"

    return ScoreFactor(
        FACTOR_GAP,
        gap,
        _clamp(normalized),
        weight,
        f"gap {gap:.2f}% sits {position:.0%} into the "
        f"{profile.gap_min}-{profile.gap_max}% band, {shape}",
    )


def score_rvol(candidate: Candidate, profile: ThresholdProfile, settings) -> ScoreFactor:
    """Volume conviction, saturating at a multiple of the threshold.

    A ticker barely over the RVOL gate scores ~0: it passed the filter but supplies no
    conviction. The signal is in the magnitude, not the qualification.
    """
    weight = settings.score_weight_rvol
    rvol = candidate.rvol_pct
    if rvol is None:
        return ScoreFactor(FACTOR_RVOL, None, 0.0, weight, "no RVOL computed", is_fallback=True)

    saturation = profile.rvol_min * settings.score_rvol_saturation_multiple
    span = max(saturation - profile.rvol_min, 1e-9)
    normalized = _clamp((rvol - profile.rvol_min) / span)

    detail = (
        f"RVOL {rvol:.1f}% against a {profile.rvol_min}% floor, "
        f"saturating at {saturation:.0f}%"
    )
    if candidate.rvol_is_approximate:
        detail += " — APPROXIMATE (not time-of-day normalized)"

    return ScoreFactor(FACTOR_RVOL, rvol, normalized, weight, detail)


def score_upside(candidate: Candidate, profile: ThresholdProfile, settings) -> ScoreFactor:
    """Room to the nearest ceiling — null-tolerant by design.

    When `upside_pct` is None the ticker has no measurable overhead resistance. That is
    UNMEASURED headroom, not bad headroom, so the factor falls back to a neutral,
    configurable score and flags itself rather than scoring 0 (which would silently bury
    such names) or 1 (which would silently promote them). Which of those is actually
    right is a strategy question deferred to live V2 experience.
    """
    weight = settings.score_weight_upside
    upside = candidate.upside_pct

    if upside is None:
        return ScoreFactor(
            FACTOR_UPSIDE,
            None,
            _clamp(settings.score_null_upside_fallback),
            weight,
            "no overhead resistance — headroom is unmeasured, scored neutrally "
            "(see docs/CLAUDE.md 4.3 'Breakout convention')",
            is_fallback=True,
        )

    saturation = profile.upside_min * settings.score_upside_saturation_multiple
    span = max(saturation - profile.upside_min, 1e-9)
    normalized = _clamp((upside - profile.upside_min) / span)

    source = candidate.resistance_source or "unknown level"
    return ScoreFactor(
        FACTOR_UPSIDE,
        upside,
        normalized,
        weight,
        f"{upside:.2f}% to {source} "
        f"({candidate.nearest_resistance:.2f}), saturating at {saturation:.1f}%",
    )


def score_liquidity(candidate: Candidate, profile: ThresholdProfile, settings) -> ScoreFactor:
    """Average dollar volume on a log scale — tradeability, not size of the move."""
    weight = settings.score_weight_liquidity
    dollar_volume = candidate.dollar_volume()

    if not dollar_volume or dollar_volume <= 0:
        return ScoreFactor(
            FACTOR_LIQUIDITY, None, 0.0, weight, "no dollar volume available", is_fallback=True
        )

    floor = max(profile.dollar_volume_min, 1.0)
    multiple = dollar_volume / floor
    saturation = max(settings.score_liquidity_saturation_multiple, 1.0000001)
    normalized = _clamp(math.log10(max(multiple, 1.0)) / math.log10(saturation))

    return ScoreFactor(
        FACTOR_LIQUIDITY,
        dollar_volume,
        normalized,
        weight,
        f"${dollar_volume:,.0f} average daily dollar volume, {multiple:.0f}x the "
        f"${floor:,.0f} floor",
    )


def score_data_quality(
    candidate: Candidate, profile: ThresholdProfile, settings, as_of: datetime | None = None
) -> ScoreFactor:
    """How much the inputs can be trusted.

    In V1 this factor is *supposed* to score low: the profile is demo, RVOL is
    approximate and Stage 2 is fixture-fed. A confident-looking score built on
    constructed inputs would be the most misleading thing this system could produce.
    """
    weight = settings.score_weight_data_quality
    score = 1.0
    penalties: list[str] = []

    if profile.is_demo:
        score -= settings.score_penalty_demo_profile
        penalties.append(f"demo profile (-{settings.score_penalty_demo_profile})")

    if candidate.rvol_is_approximate:
        score -= settings.score_penalty_approximate_rvol
        penalties.append(f"approximate RVOL (-{settings.score_penalty_approximate_rvol})")

    if candidate.snapshot_source and candidate.snapshot_source != "fmp-live":
        score -= settings.score_penalty_fixture_snapshot
        penalties.append(
            f"{candidate.snapshot_source} snapshot (-{settings.score_penalty_fixture_snapshot})"
        )

    if candidate.upside_pct is None:
        score -= settings.score_penalty_null_upside
        penalties.append(f"unmeasured headroom (-{settings.score_penalty_null_upside})")

    age_days = _reference_age_days(candidate, as_of)
    if age_days is not None and age_days > settings.score_reference_max_age_days:
        score -= settings.score_penalty_stale_reference
        penalties.append(
            f"reference data {age_days} days old (-{settings.score_penalty_stale_reference})"
        )

    detail = "all inputs nominal" if not penalties else "; ".join(penalties)
    return ScoreFactor(
        FACTOR_DATA_QUALITY, None, _clamp(score), weight, detail, is_fallback=bool(penalties)
    )


def _reference_age_days(candidate: Candidate, as_of: datetime | None) -> int | None:
    """Age of the reference data in days, if both timestamps are known."""
    if candidate.reference_computed_at is None or as_of is None:
        return None
    computed = candidate.reference_computed_at
    reference = as_of.replace(tzinfo=None) if as_of.tzinfo else as_of
    return max(0, (reference - computed).days)


def compute_confidence(
    candidate: Candidate, profile: ThresholdProfile, as_of: datetime | None = None
) -> ConfidenceScore:
    """Score one candidate, returning the value and the full breakdown."""
    settings = get_settings()

    factors = [
        score_gap(candidate, profile, settings),
        score_rvol(candidate, profile, settings),
        score_upside(candidate, profile, settings),
        score_liquidity(candidate, profile, settings),
        score_data_quality(candidate, profile, settings, as_of),
    ]

    total_weight = sum(f.weight for f in factors)
    raw = sum(f.contribution for f in factors)
    # Normalise by the actual weight total so a mis-summed config shifts nothing silently.
    score = _clamp(raw / total_weight) if total_weight else 0.0

    notes = [
        "PROVISIONAL — weights are reasoned assumptions, not backtested. "
        "Validation requires historical intraday data (app V3, Phase 6).",
    ]
    if profile.is_demo:
        notes.append("DEMO PROFILE — thresholds loosened; this candidate is illustrative only.")
    if candidate.rvol_is_approximate:
        notes.append(
            "RVOL is approximate: partial pre-market volume compared against a full-day "
            "average, not time-of-day normalized (needs FMP Premium, app V3)."
        )
    if candidate.upside_pct is None:
        notes.append(
            "Upside is unmeasured — no resistance level above the current price. The "
            "headroom factor used a neutral fallback."
        )
    if abs(total_weight - 1.0) > 1e-6:
        notes.append(
            f"Configured weights sum to {total_weight:.3f}, not 1.0; the score was "
            f"normalised by that total."
        )

    return ConfidenceScore(
        score=score, factors=factors, notes=notes, profile=profile.name, is_provisional=True
    )


def suggested_entry_window(as_of: datetime, is_final_pass: bool) -> str:
    """Human-readable entry window for the alert contract.

    Deliberately a window, not a moment, and deliberately vague before the 09:25
    confirmation pass: a pre-market candidate at 05:00 has four hours in which to stop
    being one.
    """
    if is_final_pass:
        return "09:30-10:00 ET (first 30 minutes of the regular session)"
    return f"monitor — provisional at {as_of.strftime('%H:%M')} ET, confirmed at 09:25 ET"
