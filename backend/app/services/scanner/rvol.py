"""Relative-volume (RVOL) calculation — the seam that makes tier upgrades a config change.

Two implementations behind one protocol:

  * `SimpleRvol` — accumulated pre-market volume as a percentage of the 20-day average
    DAILY volume. Crude (it compares a partial session against a full one) but it is
    what FMP's Starter tier can support, so it is what app V2 ships. Results are always
    flagged approximate.

  * `NormalizedRvol` — the spec's time-of-day-normalized version: today's accumulated
    pre-market volume against what this ticker had typically accumulated by this same
    clock time. It needs `extended=true` pre-market intraday bars, which FMP support
    confirmed is Premium-only, so in V1/V2 it raises rather than guessing.

Selected via `RVOL_MODE`. Upgrading tiers later must be a config change, not a rewrite —
that is the entire point of this module existing before it is needed.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from app.config import get_settings
from app.services.scanner.errors import FeatureRequiresIntraday, InsufficientRvolData

MODE_SIMPLE = "simple"
MODE_NORMALIZED = "normalized"


@dataclass(frozen=True)
class RvolContext:
    """Inputs for one RVOL calculation."""

    ticker: str
    volume_premarket_accumulated: float | None
    volume_avg_20d: float | None
    # ET-aware timestamp of the scan. Injected, never read from the wall clock, so any
    # point in the 04:00–09:25 window can be simulated in tests.
    as_of: datetime | None = None
    # bucket_minute -> avg cumulative pre-market volume. Populated from V3 onwards.
    premarket_volume_profile: dict[int, float] = field(default_factory=dict)


@dataclass(frozen=True)
class RvolResult:
    """An RVOL value plus the honesty metadata that must reach the alert payload."""

    rvol_pct: float
    mode: str
    is_approximate: bool
    detail: str


@runtime_checkable
class RvolCalculator(Protocol):
    """Computes relative volume as a percentage."""

    mode: str

    def compute(self, ctx: RvolContext) -> RvolResult:
        """Return the RVOL percentage, or raise if the inputs cannot support one."""
        ...


class SimpleRvol:
    """premarket_volume / volume_avg_20d * 100.

    Comparing a partial pre-market session against a full-day average understates RVOL
    and does so unevenly across the session — 04:05 and 09:20 are not comparable. Hence
    `is_approximate=True` on every result; the UI must surface it.
    """

    mode = MODE_SIMPLE

    def compute(self, ctx: RvolContext) -> RvolResult:
        if ctx.volume_premarket_accumulated is None:
            raise InsufficientRvolData(
                f"{ctx.ticker}: no accumulated pre-market volume available for RVOL"
            )
        if not ctx.volume_avg_20d:
            raise InsufficientRvolData(
                f"{ctx.ticker}: volume_avg_20d is missing or zero; RVOL is undefined "
                f"(refresh reference data before scanning)"
            )

        rvol_pct = ctx.volume_premarket_accumulated / ctx.volume_avg_20d * 100
        return RvolResult(
            rvol_pct=rvol_pct,
            mode=self.mode,
            is_approximate=True,
            detail=(
                "Partial pre-market volume compared against the 20-day full-day average; "
                "not time-of-day normalized."
            ),
        )


class NormalizedRvol:
    """Time-of-day-normalized RVOL, per `docs/CLAUDE.md` section 4.2.

    Deliberately raises in V1/V2 instead of silently degrading to the simple formula: an
    RVOL that claims to be normalized but is not would corrupt every threshold decision
    downstream, and quietly at that.
    """

    mode = MODE_NORMALIZED

    def compute(self, ctx: RvolContext) -> RvolResult:
        if not ctx.premarket_volume_profile:
            raise FeatureRequiresIntraday(
                f"{ctx.ticker}: time-of-day-normalized RVOL needs a pre-market volume "
                f"profile, which is built from `extended=true` intraday bars. That "
                f"parameter requires FMP Premium (app V3) — FMP's Starter tier serves "
                f"regular-hours bars only. Set RVOL_MODE=simple until then."
            )
        if ctx.as_of is None:
            raise InsufficientRvolData(
                f"{ctx.ticker}: normalized RVOL needs an `as_of` timestamp to pick the "
                f"time-of-day bucket"
            )
        if ctx.volume_premarket_accumulated is None:
            raise InsufficientRvolData(
                f"{ctx.ticker}: no accumulated pre-market volume available for RVOL"
            )

        expected = _expected_volume_at(ctx)
        if not expected:
            raise InsufficientRvolData(
                f"{ctx.ticker}: no expected pre-market volume for bucket at {ctx.as_of}"
            )

        return RvolResult(
            rvol_pct=ctx.volume_premarket_accumulated / expected * 100,
            mode=self.mode,
            is_approximate=False,
            detail="Accumulated pre-market volume vs. the 20-session average at this clock time.",
        )


def _expected_volume_at(ctx: RvolContext) -> float | None:
    """Look up the profile bucket at or before `as_of` (minutes since 04:00 ET)."""
    assert ctx.as_of is not None
    minutes = (ctx.as_of.hour - 4) * 60 + ctx.as_of.minute
    candidates = [b for b in ctx.premarket_volume_profile if b <= minutes]
    if not candidates:
        return None
    return ctx.premarket_volume_profile[max(candidates)]


_IMPLEMENTATIONS: dict[str, type] = {
    MODE_SIMPLE: SimpleRvol,
    MODE_NORMALIZED: NormalizedRvol,
}


def get_rvol_calculator(mode: str | None = None) -> RvolCalculator:
    """Build the calculator named by `mode`, defaulting to the `RVOL_MODE` setting."""
    resolved = (mode or get_settings().rvol_mode).strip().lower()
    try:
        return _IMPLEMENTATIONS[resolved]()
    except KeyError:
        raise ValueError(
            f"Unknown RVOL mode {resolved!r}; expected one of {sorted(_IMPLEMENTATIONS)}"
        ) from None
