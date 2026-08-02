"""Threshold profiles.

Thresholds live in configuration, not code, because the end user's strategy will evolve
and tuning must never require a deploy.

Two profiles ship:

  * `production` — the real specification from `docs/CLAUDE.md` section 4.3.
  * `demo`       — identical except for a loosened float cap.

The demo profile is not a convenience. Every symbol the FMP free tier serves is a mega-cap
whose float is in the billions, roughly 1000x the 75M production cap, so on real V1 data
the production profile is *structurally incapable* of producing a candidate. Without a
demo profile there is nothing to see end to end. It changes one threshold and leaves the
rest alone, so what runs in demo is the same logic that runs in production.

Because demo output is deliberately not trustworthy, `is_demo` is stamped into
`scan_runs`, onto every candidate, and (from Phase 3) onto every alert payload and UI
card. Demo output must never be mistakable for real output.
"""

from dataclasses import dataclass, replace

from app.config import get_settings

PRODUCTION = "production"
DEMO = "demo"


@dataclass(frozen=True)
class ThresholdProfile:
    """One complete set of scanner thresholds."""

    name: str
    # Stage 1 — structural liquidity
    float_max: int
    avg_volume_min: float
    # Stage 2 — momentum
    gap_min: float
    gap_max: float
    rvol_min: float
    # Stage 3 — room to run
    upside_min: float
    # Risk filters
    price_floor: float
    dollar_volume_min: float

    # NOTE: there is deliberately no `description` field.
    #
    # There used to be, holding a sentence like "float cap loosened to 20,000,000,000".
    # `resolve_profile()` applies stored overrides with `replace(profile, **applied)`,
    # which updates the numbers and leaves that sentence untouched — so a single run
    # printed the effective cap in one line and the designed cap in the next. A
    # hardcoded string that duplicates configuration is a second source of truth and
    # will go stale again. Every summary below is derived from the fields at call time.

    @property
    def is_demo(self) -> bool:
        """Whether this profile's output is illustrative rather than actionable."""
        return self.name != PRODUCTION

    def threshold_summary(self) -> str:
        """The stage thresholds actually in effect, one line."""
        return (
            f"float < {self.float_max:,} | avg vol > {self.avg_volume_min:,.0f} | "
            f"gap {self.gap_min}-{self.gap_max}% | rvol > {self.rvol_min}% | "
            f"upside >= {self.upside_min}%"
        )

    def risk_summary(self) -> str:
        """The risk filters actually in effect, one line."""
        return (
            f"price >= ${self.price_floor} | "
            f"dollar volume >= ${self.dollar_volume_min:,.0f}"
        )

    def describe(self) -> str:
        """Full human-readable description, derived — safe to show anywhere."""
        if self.is_demo:
            return (
                f"DEMO — float cap loosened to {self.float_max:,} so free-tier mega-caps "
                f"can reach Stage 1. Output is illustrative, NOT actionable. "
                f"Effective: {self.threshold_summary()}"
            )
        return f"Production thresholds (docs/CLAUDE.md 4.3). Effective: {self.threshold_summary()}"

    def as_dict(self) -> dict:
        """Flat mapping for stamping into `scan_runs.stage_counts_json` and payloads."""
        return {
            "name": self.name,
            "is_demo": self.is_demo,
            "float_max": self.float_max,
            "avg_volume_min": self.avg_volume_min,
            "gap_min": self.gap_min,
            "gap_max": self.gap_max,
            "rvol_min": self.rvol_min,
            "upside_min": self.upside_min,
            "price_floor": self.price_floor,
            "dollar_volume_min": self.dollar_volume_min,
            "summary": self.threshold_summary(),
        }


def production_profile() -> ThresholdProfile:
    """The real specification, read from settings so it is tunable without a redeploy."""
    settings = get_settings()
    return ThresholdProfile(
        name=PRODUCTION,
        float_max=settings.scan_float_max,
        avg_volume_min=settings.scan_avg_volume_min,
        gap_min=settings.scan_gap_min,
        gap_max=settings.scan_gap_max,
        rvol_min=settings.scan_rvol_min,
        upside_min=settings.scan_upside_min,
        price_floor=settings.scan_price_floor,
        dollar_volume_min=settings.scan_dollar_volume_min,
    )


def demo_profile() -> ThresholdProfile:
    """Production thresholds with only the float cap loosened."""
    settings = get_settings()
    return replace(
        production_profile(),
        name=DEMO,
        float_max=settings.scan_demo_float_max,
    )


_BUILDERS = {
    PRODUCTION: production_profile,
    DEMO: demo_profile,
}


def get_profile(name: str | None = None) -> ThresholdProfile:
    """Build the named profile, defaulting to the `SCAN_PROFILE` setting."""
    resolved = (name or get_settings().scan_profile).strip().lower()
    try:
        return _BUILDERS[resolved]()
    except KeyError:
        raise ValueError(
            f"Unknown threshold profile {resolved!r}; expected one of {sorted(_BUILDERS)}"
        ) from None


def available_profiles() -> list[str]:
    return sorted(_BUILDERS)
