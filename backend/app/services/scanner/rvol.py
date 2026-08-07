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

from dataclasses import dataclass, field, replace
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
    # bucket_minute -> avg cumulative pre-market volume. Populated from Phase 4B.
    premarket_volume_profile: dict[int, float] = field(default_factory=dict)
    # **The symmetry field.** The instant through which `volume_premarket_accumulated` is
    # actually complete, which is EARLIER than `as_of` whenever provisional bars were
    # excluded. The profile bucket is chosen from this, not from `as_of` — see
    # `_expected_volume_at`. None means "the numerator is complete as of `as_of`".
    settled_through: datetime | None = None
    # How many sessions the profile was averaged over. Below the configured minimum the
    # caller degrades to SimpleRvol rather than dividing by a noisy denominator.
    profile_sessions_sampled: int | None = None


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
                f"profile, and this ticker has none. Profiles are built by "
                f"`scripts/build_volume_profiles.py` from `extended=true` intraday bars "
                f"(FMP Premium, active since 5 Aug 2026) for the Stage-1 set. A ticker "
                f"that has just entered the universe will not have one until the next "
                f"nightly build; `NormalizedRvolWithFallback` degrades to SimpleRvol and "
                f"flags the alert rather than skipping the candidate."
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
    """Look up the profile bucket at or before the numerator's cut-off.

    **This is the settled-bar symmetry rule, and it is the whole reason RVOL can be
    trusted.** The denominator comes from `premarket_volume_profile`, built in Phase 4B
    from fully-settled historical bars. The numerator, on a live pass, is a sum over bars
    that were old enough to trust — which stops ~7 minutes short of `as_of`.

    Keying this lookup off `as_of` would therefore compare *volume accumulated by 09:13*
    against *volume normally reached by 09:25*. Every ticker would look quieter than it is,
    by however much the market usually trades in those minutes, and the error lands
    directly on the `rvol_pct > 10` gate. There is no symptom: alerts simply do not fire,
    and no log line says why.

    So the bucket is chosen from `settled_through` when the provider supplied one, and only
    falls back to `as_of` when the numerator genuinely is complete to that instant (the
    fixture provider, whose volumes are authored rather than accumulated).
    """
    reference = ctx.settled_through or ctx.as_of
    assert reference is not None
    minutes = (reference.hour - 4) * 60 + reference.minute
    candidates = [b for b in ctx.premarket_volume_profile if b <= minutes]
    if not candidates:
        return None
    return ctx.premarket_volume_profile[max(candidates)]


class NormalizedRvolWithFallback:
    """Normalized where the profile supports it; SimpleRvol, **clearly flagged**, where it
    does not.

    `NormalizedRvol` is deliberately strict — it raises rather than quietly producing a
    number that claims to be time-of-day normalized and is not. That strictness is right,
    but on its own it would make a live scan drop every candidate whose profile is missing
    or thin, which is precisely the newly-listed, newly-liquid names the strategy most
    wants to catch. A ticker that entered the universe last night has no profile until the
    next nightly build.

    So this degrades instead of skipping — and the degraded result keeps `mode="simple"`
    and `is_approximate=True` straight from `SimpleRvol`. The two are never blended into a
    number that looks normalized: the alert carries the simple mode, the UI's existing
    approximate badge fires, and the reason is spelled out in `detail`.
    """

    mode = MODE_NORMALIZED

    def __init__(self) -> None:
        self._normalized = NormalizedRvol()
        self._simple = SimpleRvol()

    def compute(self, ctx: RvolContext) -> RvolResult:
        minimum = get_settings().profile_sessions_min

        if not ctx.premarket_volume_profile:
            return self._degrade(ctx, "no pre-market volume profile for this ticker")

        sampled = ctx.profile_sessions_sampled
        if sampled is not None and sampled < minimum:
            return self._degrade(
                ctx,
                f"profile averaged over only {sampled} session(s), below the "
                f"{minimum}-session minimum",
            )

        try:
            return self._normalized.compute(ctx)
        except FeatureRequiresIntraday as exc:
            return self._degrade(ctx, str(exc))
        except InsufficientRvolData as exc:
            # A missing bucket at this clock time — e.g. scanning at 04:02 for a ticker
            # whose profile starts later. Degrading beats discarding the candidate.
            if ctx.volume_avg_20d:
                return self._degrade(ctx, str(exc))
            raise

    def _degrade(self, ctx: RvolContext, why: str) -> RvolResult:
        result = self._simple.compute(ctx)
        return replace(
            result,
            detail=f"DEGRADED to simple RVOL — {why}. {result.detail}",
        )


_IMPLEMENTATIONS: dict[str, type] = {
    MODE_SIMPLE: SimpleRvol,
    # The fallback-capable variant, not the strict one: a live scan must not lose a
    # candidate merely because its profile has not been built yet.
    MODE_NORMALIZED: NormalizedRvolWithFallback,
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
