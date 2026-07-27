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

    description: str = ""

    @property
    def is_demo(self) -> bool:
        """Whether this profile's output is illustrative rather than actionable."""
        return self.name != PRODUCTION

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
        description="Production thresholds from docs/CLAUDE.md section 4.3.",
    )


def demo_profile() -> ThresholdProfile:
    """Production thresholds with only the float cap loosened."""
    settings = get_settings()
    return replace(
        production_profile(),
        name=DEMO,
        float_max=settings.scan_demo_float_max,
        description=(
            f"DEMO — float cap loosened to {settings.scan_demo_float_max:,} so free-tier "
            f"mega-caps can reach Stage 1. Output is illustrative, NOT actionable."
        ),
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
