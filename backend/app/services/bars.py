"""Intraday bar handling: the pre-market window, bucketing, and the **settled-bar rule**.

This module exists so that ONE definition of "settled" is shared by everything that
divides one volume figure by another. It is deliberately provider-agnostic and has no
database or FMP imports.

## Why the settled-bar rule exists

Phase 4A measured FMP's pre-market bars across 16 samples of a live session
(`docs/FMP_PREMIUM_FINDINGS.md` §3):

- **89 of 180 re-observed bars (49.4%) changed volume** between identical requests.
- **All 89 were revised upward, none downward.** Median +24.2%, worst case +7,156% —
  one bar first reported as 16 shares finished at 1,161.
- Every revision landed **within 7 minutes of the bar closing**; none later.

So a freshly published bar is provisional. Reading it as final understates volume.

## The coupling that makes this critical, not cosmetic

In Phase 4C, RVOL divides a **live numerator** (volume accumulated so far today) by a
**profile denominator** (the average cumulative volume this ticker had reached by the same
clock time, built here in Phase 4B).

The denominator is built from *history*, which is fully settled. If the numerator includes
provisional bars while the denominator does not, RVOL is biased **low by construction** —
by roughly the median revision, on exactly the most recent bars, which are the ones that
signal a stock is moving *now*. That bias lands directly on the `rvol_pct > 10` gate and
suppresses real candidates.

**Both sides must use `settled_bars()` with the same exclusion window, and must compare the
same bucket_minute.** This is the kind of coupling that is invisible until alert counts come
in mysteriously low and nobody can say why, which is why the rule lives in one place rather
than being applied twice.

The exclusion window comes from config (`BAR_SETTLE_MINUTES`), never a literal: the
7-minute figure is one ordinary session's measurement, and a volatile or holiday-shortened
morning could report later.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.config import get_settings

# The scanner's pre-market window, per docs/CLAUDE.md §4.5. 04:00 is not a guess: Phase 4A
# confirmed FMP's first extended-hours bar of every session is stamped exactly 04:00 ET,
# on sessions going back to 2016.
PREMARKET_OPEN = time(4, 0)
PREMARKET_CUTOFF = time(9, 30)

# Bucket granularity for premarket_volume_profile: minutes since 04:00 ET.
DEFAULT_BAR_MINUTES = 5


def market_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().scanner_timezone)


@dataclass(frozen=True)
class Bar:
    """One intraday bar, timestamped at its OPENING edge.

    FMP stamps bars this way: a bar labelled 04:00 covers [04:00, 04:05). The distinction
    matters for settling — a bar is not even complete until `end` has passed.
    """

    start: datetime
    volume: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    interval_minutes: int = DEFAULT_BAR_MINUTES

    @property
    def end(self) -> datetime:
        """When this bar closed. A 04:00 five-minute bar closes at 04:05."""
        return self.start + timedelta(minutes=self.interval_minutes)

    @property
    def bucket_minute(self) -> int:
        """Minutes since 04:00 ET — the profile's join key."""
        return bucket_minute(self.start)


def bucket_minute(moment: datetime) -> int:
    """Minutes elapsed since 04:00 ET on the same day.

    Negative before 04:00, which callers should treat as out of window rather than
    clamping to zero — silently folding 03:55 into bucket 0 would corrupt the profile's
    first bucket with data from outside the session.
    """
    open_at = moment.replace(
        hour=PREMARKET_OPEN.hour, minute=PREMARKET_OPEN.minute, second=0, microsecond=0
    )
    return int((moment - open_at).total_seconds() // 60)


def is_premarket(moment: datetime) -> bool:
    return PREMARKET_OPEN <= moment.timetz().replace(tzinfo=None) < PREMARKET_CUTOFF


def premarket_bars(bars: list[Bar]) -> list[Bar]:
    """Bars whose opening edge falls inside 04:00 <= t < 09:30 ET, sorted by time."""
    return sorted((b for b in bars if is_premarket(b.start)), key=lambda b: b.start)


def is_settled(bar: Bar, now: datetime, exclusion_minutes: int | None = None) -> bool:
    """Has this bar stopped being revised?

    True once `now` is at least `exclusion_minutes` past the bar's CLOSE. A bar still in
    progress is never settled.
    """
    minutes = _exclusion(exclusion_minutes)
    return now >= bar.end + timedelta(minutes=minutes)


def settled_bars(
    bars: list[Bar], now: datetime | None = None, exclusion_minutes: int | None = None
) -> list[Bar]:
    """The subset of `bars` safe to treat as final. **Use this on both sides of RVOL.**

    Passing `now=None` means "everything here is historical", which is true for previous
    sessions and is how the profile builder calls it. The live path must always pass a
    real clock, or it will treat provisional bars as final and understate volume.
    """
    ordered = sorted(bars, key=lambda b: b.start)
    if now is None:
        return ordered
    minutes = _exclusion(exclusion_minutes)
    return [b for b in ordered if now >= b.end + timedelta(minutes=minutes)]


def cumulative_by_bucket(bars: list[Bar]) -> dict[int, float]:
    """Running sum of volume, keyed by minutes since 04:00.

    **Volume is per-bar, not cumulative** — Phase 4A established this by measurement
    (AAPL 30,243 -> 9,965 -> 2,822 across consecutive bars, which a cumulative counter
    cannot do). So the cumulative figure the scanner needs is a running sum, and any code
    that reads a single bar's `volume` as "volume so far" silently gets the last five
    minutes instead of the session.
    """
    running = 0.0
    out: dict[int, float] = {}
    for bar in premarket_bars(bars):
        running += bar.volume or 0.0
        out[bar.bucket_minute] = running
    return out


def _exclusion(explicit: int | None) -> int:
    return get_settings().bar_settle_minutes if explicit is None else explicit
