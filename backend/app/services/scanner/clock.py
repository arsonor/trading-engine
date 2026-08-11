"""Injectable clock and market-time handling.

Two rules govern every timestamp in the scanner:

1. **No scanner logic calls `datetime.now()`.** The clock is injected, so any moment in
   the 04:00–09:25 ET window — including both DST transitions — can be simulated.

2. **Market logic is in America/New_York, never UTC.** Render's cron runs in UTC. A
   UTC-pinned 08:00 schedule is 03:00 ET in winter and 04:00 ET in summer, so half the
   year it would fire outside the scan window entirely. The cron is therefore scheduled
   generously in UTC and the real work is gated on a computed ET timestamp.

3. **Window decisions are made at minute resolution.** Every comparison against the
   window bounds goes through `at_minute()`, so the timestamp printed in a log is
   literally the timestamp that was compared. See `at_minute()` for why.

`test_scanner_clock.py` pins that drift with the same UTC instant landing on different
sides of the window boundary in January and July.
"""

from datetime import datetime, time, timedelta, timezone
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# The pre-market scan window, per docs/CLAUDE.md section 4.5.
SCAN_WINDOW_START = time(4, 0)
SCAN_WINDOW_END = time(9, 25)

# The 09:25 pass is the final confirmation run: the one whose alert set is definitive.
FINAL_PASS_TIME = time(9, 25)

# Cadence of the scan window (informational; the cron schedule owns the real interval).
SCAN_INTERVAL_MINUTES = 5


@runtime_checkable
class Clock(Protocol):
    """Supplies the current moment in Eastern Time."""

    def now_et(self) -> datetime:
        """Current time as a timezone-aware America/New_York datetime."""
        ...


class SystemClock:
    """Wall-clock time, converted to ET. The only place `datetime.now()` is called."""

    def now_et(self) -> datetime:
        return datetime.now(timezone.utc).astimezone(ET)


class FixedClock:
    """A clock frozen at one moment — how tests and `--at` simulate any scan time."""

    def __init__(self, moment: datetime) -> None:
        self._moment = to_et(moment)

    def now_et(self) -> datetime:
        return self._moment

    def __repr__(self) -> str:
        return f"FixedClock({self._moment.isoformat()})"


def to_et(moment: datetime) -> datetime:
    """Convert any datetime to ET.

    A naive datetime is interpreted as ET, not UTC: every naive timestamp in this system
    comes from a human writing a market time (`--at "2026-07-28 08:45"`), and silently
    reading that as UTC would shift the scan by four hours.
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=ET)
    return moment.astimezone(ET)


def to_utc(moment: datetime) -> datetime:
    """Convert any datetime to UTC (naive input is treated as ET, as in `to_et`)."""
    return to_et(moment).astimezone(timezone.utc)


def at_minute(moment: datetime) -> datetime:
    """The ET moment with seconds and microseconds discarded.

    **The value shown and the value decided on must be the same value.** Render's
    scheduler starts a job 10–45 s after its scheduled minute, so the 13:25 UTC cron —
    the authoritative 09:25 ET pass — actually begins around 09:25:10 ET. Comparing full
    timestamps made `09:25:10 > 09:25:00` true, and the single most important pass of the
    day was silently skipped while the log header, rendered at minute resolution, printed
    "09:25" and claimed it was outside a window ending at 09:25.

    Truncating is the fix, not a grace period: §4.5 specifies a window of 04:00–09:25,
    not 04:00:00.000–09:25:00.000, and truncation is independent of how late the
    scheduler happens to be rather than tolerant of one particular amount of lateness.
    Same correction, and the same reason, as rounding percentages before comparing them
    against a threshold in Phase 2.
    """
    return to_et(moment).replace(second=0, microsecond=0)


def is_within_scan_window(moment: datetime) -> bool:
    """Whether an ET moment falls in the 04:00–09:25 pre-market scan window.

    Inclusive at both ends, at minute resolution: 04:00 opens the window and 09:25 is
    the final pass, which must run. Both bounds are truncated, so 07:59:58 ET is 07:59
    and does not sneak past a bound it has not yet reached — the lower bound has the
    same class of edge as the upper one, currently masked only because the 08:00 UTC run
    starts after 04:00 ET rather than before it.
    """
    return SCAN_WINDOW_START <= at_minute(moment).time() <= SCAN_WINDOW_END


def is_final_pass(moment: datetime) -> bool:
    """Whether this is the 09:25 confirmation run whose alert set is definitive."""
    return at_minute(moment).time() >= FINAL_PASS_TIME


def minutes_since_window_open(moment: datetime) -> int:
    """Minutes elapsed since 04:00 ET — the bucket index for volume profiles (V3)."""
    et = to_et(moment)
    return (et.hour - SCAN_WINDOW_START.hour) * 60 + (et.minute - SCAN_WINDOW_START.minute)


def scan_times_for(day: datetime) -> list[datetime]:
    """Every scheduled scan moment on a given ET date, 04:00 → 09:25 inclusive.

    Built by adding wall-clock minutes in ET, so a DST transition inside the window
    yields the correct number of runs rather than a UTC-arithmetic drift.
    """
    et = to_et(day)
    start = et.replace(
        hour=SCAN_WINDOW_START.hour, minute=SCAN_WINDOW_START.minute, second=0, microsecond=0
    )
    end = et.replace(
        hour=SCAN_WINDOW_END.hour, minute=SCAN_WINDOW_END.minute, second=0, microsecond=0
    )

    times: list[datetime] = []
    current = start
    while current <= end:
        times.append(current)
        current += timedelta(minutes=SCAN_INTERVAL_MINUTES)
    return times


def parse_scan_time(raw: str) -> datetime:
    """Parse a CLI `--at` value into an ET-aware datetime.

    Accepts `"2026-07-28 08:45"`, `"2026-07-28 08:45 ET"`, `"2026-07-28T08:45"` and full
    ISO strings with an offset. A bare time is always read as ET.
    """
    text = raw.strip()
    for suffix in (" ET", " EST", " EDT", " et"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            break

    text = text.replace(" ", "T", 1) if " " in text and "T" not in text else text

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            f"Could not parse --at value {raw!r}. Expected something like "
            f'"2026-07-28 08:45" or "2026-07-28 08:45 ET".'
        ) from exc

    return to_et(parsed)


def describe(moment: datetime) -> str:
    """Human-readable ET stamp with the offset, so EST/EDT is always visible in logs.

    Goes through `at_minute` rather than formatting with `%H:%M`, so this string cannot
    drift away from what the window gate decided on: same function, same value.
    """
    et = at_minute(moment)
    return f"{et.strftime('%Y-%m-%d %H:%M')} {et.tzname()} (UTC{et.strftime('%z')[:3]})"
