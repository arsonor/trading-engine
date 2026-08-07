"""Data-integrity guards for the live scan.

These do not change what the stages decide. They **observe** and **record**, because the
failure mode they guard against is not a crash — it is a confident, plausible, wrong
number reaching a user who has no way to check it.

Three guards, each from a specific measurement rather than a general worry:

1. **Monotonicity.** The Tiingo probe found a low-float ticker whose cumulative volume
   reset to zero mid-session and re-accumulated from a new baseline, permanently losing the
   earlier total, with every row looking healthy in isolation. Phase 4A found no such reset
   on FMP — but that is one session's absence of evidence, not a guarantee, and the cost of
   checking is a dictionary lookup.

2. **Volume sanity.** An accumulated pre-market volume tens of times the 20-day average is
   more often a data fault than a real event. Flagged, never dropped: a genuine 30x morning
   is precisely what the scanner exists to find, so the operator decides, not this module.

3. **Price-regime break.** A 20-day high several times the current close.

   **This guard was introduced in Phase 4C under the name `split_distortion`, and that
   diagnosis was wrong.** It was assumed that FMP returned unadjusted history and that a
   reverse split was leaving pre-split levels in `reference_data`. Measured 8 August 2026
   against the seven flagged tickers, that is false: `historical-price-eod/full` is
   ALREADY split-adjusted. FFAI's June bars come back at 42.42 with volume 97,942 while
   the raw tape (`historical-price-eod/non-split-adjusted`) shows 0.2828 with volume
   14,691,299 — price and volume ratios both exactly 150.0, which only holds if `full` is
   the adjusted series. Five of the seven had no split at all.

   What the guard actually detects is a **real collapse**: FFAI fell 32.06 -> 4.38 in
   twenty sessions, WETO 67.07 -> 5.77. The reference data is correct; the resistance
   levels are simply from a price regime that no longer exists, so "540% upside to the
   50-day average" is arithmetically right and strategically meaningless. There is no
   magnet at the 50-day average — it is merely where the stock used to be.

   The finding is kept because the tickers it identifies are still the wrong ones to
   surface. Only the explanation changed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.config import get_settings
from app.services.scanner.candidate import Candidate

logger = logging.getLogger(__name__)

GUARD_VOLUME_DECREASED = "volume_decreased"
GUARD_VOLUME_IMPLAUSIBLE = "volume_implausible"
GUARD_PRICE_REGIME_BREAK = "price_regime_break"


@dataclass
class IntegrityFinding:
    ticker: str
    guard: str
    detail: str

    def __str__(self) -> str:
        return f"{self.ticker}: {self.guard} — {self.detail}"


@dataclass
class VolumeMonotonicityGuard:
    """Remembers each ticker's high-water accumulated volume within a session.

    Held in memory by the caller across passes. A cron process that runs one pass and exits
    has nothing to compare against, which is why the guard reports rather than enforces:
    the useful deployment is a long-lived scanner, and a per-pass process simply records
    nothing. Persisting the high-water mark would be a schema change for a check that has
    never yet fired on FMP.
    """

    seen: dict[str, float] = field(default_factory=dict)
    findings: list[IntegrityFinding] = field(default_factory=list)

    def check(self, ticker: str, accumulated: float) -> float:
        """Return the value to use — the previous high-water mark if this one went down."""
        previous = self.seen.get(ticker)
        if previous is not None and accumulated < previous:
            finding = IntegrityFinding(
                ticker,
                GUARD_VOLUME_DECREASED,
                f"accumulated pre-market volume fell {previous:,.0f} -> {accumulated:,.0f} "
                f"within the session. Volume cannot un-trade, so this is a data fault. "
                f"Keeping the higher figure and treating this ticker's RVOL as suspect.",
            )
            self.findings.append(finding)
            logger.error("INTEGRITY %s", finding)
            return previous

        self.seen[ticker] = max(accumulated, previous or 0.0)
        return accumulated


def check_volume_plausibility(
    candidate: Candidate, accumulated: float, multiple: float | None = None
) -> IntegrityFinding | None:
    """Flag an accumulated volume far above the ticker's own 20-day average."""
    limit = multiple if multiple is not None else get_settings().scan_volume_sanity_multiple
    if not candidate.volume_avg_20d or accumulated <= 0:
        return None

    ratio = accumulated / candidate.volume_avg_20d
    if ratio < limit:
        return None

    return IntegrityFinding(
        candidate.ticker,
        GUARD_VOLUME_IMPLAUSIBLE,
        f"pre-market volume {accumulated:,.0f} is {ratio:.0f}x the 20-day average "
        f"({candidate.volume_avg_20d:,.0f}), above the {limit:g}x sanity bound. Flagged, "
        f"not dropped — a real event of this size is what the scanner is for.",
    )


def check_price_regime_break(
    candidate: Candidate, multiple: float = 3.0
) -> IntegrityFinding | None:
    """Flag a ticker whose 20-day high is far above its current price.

    Measured, not assumed: this is a REAL collapse, not bad data (see the module
    docstring). The consequence is the same either way — every resistance level for the
    ticker sits in a price regime the stock has left, so the computed `upside_pct` is a
    number without a thesis behind it.

    Detected against `high_20d` rather than the SMAs because twenty sessions is short
    enough that only a genuine collapse reaches this ratio.
    """
    close = candidate.price_close_yesterday
    high = candidate.high_20d
    if not close or not high or close <= 0:
        return None

    ratio = high / close
    if ratio < multiple:
        return None

    return IntegrityFinding(
        candidate.ticker,
        GUARD_PRICE_REGIME_BREAK,
        f"20-day high {high:,.2f} is {ratio:.1f}x the prior close {close:,.2f} — the stock "
        f"has collapsed out of the price regime its resistance levels describe. The data is "
        f"correct; the resulting upside% is arithmetically right but has no thesis behind "
        f"it, since there is no magnet at a level the stock merely used to trade at.",
    )
