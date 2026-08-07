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

3. **Split distortion.** Measured on FFAI, 7 August 2026: close 4.63, 20-day high 32.17,
   SMA-200 94.32. A 20-day high seven times the close is the signature of unadjusted
   history across a reverse split, and it produces a resistance level — and therefore an
   "upside" — that does not exist. Left unflagged this is the worst kind of bad alert: it
   looks like the best opportunity on the list.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.config import get_settings
from app.services.scanner.candidate import Candidate

logger = logging.getLogger(__name__)

GUARD_VOLUME_DECREASED = "volume_decreased"
GUARD_VOLUME_IMPLAUSIBLE = "volume_implausible"
GUARD_SPLIT_DISTORTION = "split_distortion"


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


def check_split_distortion(
    candidate: Candidate, multiple: float = 3.0
) -> IntegrityFinding | None:
    """Flag reference data whose highs are impossibly far above the last close.

    A 20-day high several times the prior close cannot happen in twenty sessions of
    ordinary trading; it means the historical bars were not adjusted for a split, so every
    resistance level derived from them — and the `upside_pct` the user is shown — is
    fiction. Detected against `high_20d` rather than the SMAs because twenty sessions is a
    short enough window that no legitimate move reaches this ratio.
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
        GUARD_SPLIT_DISTORTION,
        f"20-day high {high:,.2f} is {ratio:.1f}x the prior close {close:,.2f}. Twenty "
        f"sessions cannot produce that spread; the EOD history is almost certainly "
        f"unadjusted across a split, which makes every resistance level and the resulting "
        f"upside% fictional. Refresh reference data for this ticker before trusting it.",
    )
