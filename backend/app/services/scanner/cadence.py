"""When the scanner is allowed to work: the tiered pre-market cadence.

Render's cron wakes this process every five minutes. Which of those wake-ups become real
scans is decided here, from config, against a measured shape of the morning.

## Why this is not a uniform 5-minute cadence any more

Profiled from `scan_runs` across six live sessions (10-14 and 17 August 2026, 394
completed passes) with `scripts/cadence_profile.py`:

* **04:00, 04:05 and 04:10 produced a Stage 2 survivor in none of 18 session-passes.**
  Not a quiet market — a structural impossibility. A bar is provisional until
  `BAR_SETTLE_MINUTES` (7) after it closes, so the 04:00 bar is not trusted until ~04:12
  and those three passes cannot produce a candidate by construction. The earliest pass
  that has ever produced one, and the earliest productive in *every* session, is 04:15.
* **Half the session's passes carry a seventh of its information.** Between 04:25 and
  06:55 the 32 passes surface ~1.4 tickers per session that were still candidates at
  09:25 — between them.
* **The last 40 minutes are the opposite**: 73% of what they surface first is still a
  candidate at the final pass. That window stays at five minutes.

## Why coarsening early passes cannot change the alert set

**Scans are stateless.** The 09:25 pass recomputes every ticker from all bars since
04:00, independent of what ran before it, and alerts dedup per `(ticker, session)`. A run
of passes each reporting 20 candidates is one candidate set re-reported 20 times, not 20
passes' worth of information. Cadence therefore governs dashboard freshness before 09:25
and the completeness of the faded record — never what the user is told at 09:25.

Two structural guarantees make that a property of the code rather than of the current
config values:

1. **The authoritative pass cannot be configured away.** `slots()` always ends with
   `SCAN_WINDOW_END`, whatever the tiers say. No spec, however wrong, can silence 09:25.
2. **The profile bucket epoch is not the window start.** `premarket_volume_profile` is
   keyed on minutes since 04:00 ET (`app.services.bars.bucket_minute`) and holds stored
   rows; moving the scan window to 04:15 must not move that join key by 15 minutes. The
   two constants live in different modules for exactly this reason, and
   `test_scanner_cadence.py` pins it.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from app.services.scanner.clock import SCAN_WINDOW_END, at_minute, to_et

# The measured shape, as a spec string: `HH:MM/interval` per tier, comma-separated.
#
# One string rather than four settings because the tiers are only meaningful together —
# a boundary edited without its neighbour is how a gap or an overlap gets introduced.
# The first tier's start IS the window start, so "when does the scanner open?" and "how
# often does it scan then?" cannot drift apart.
DEFAULT_CADENCE_SPEC = "04:15/60,07:00/30,08:00/15,08:30/5"

# Exact-minute matching by default: `at_minute` already absorbs the 10-45 s of scheduler
# lateness Render actually exhibits. See `Cadence.grace_minutes` before raising it.
DEFAULT_GRACE_MINUTES = 0

# An ordinary weekday, used only to count a session's passes. The slot list is built from
# ET wall-clock arithmetic, so the count does not depend on which day it is asked about.
REFERENCE_DAY = datetime(2026, 7, 28)


class CadenceError(ValueError):
    """A cadence spec that cannot be honoured. Raised at startup, never at scan time."""


@dataclass(frozen=True)
class CadenceTier:
    """One stretch of the morning and how often it is sampled."""

    start: time
    interval_minutes: int

    def describe(self) -> str:
        return f"{self.start.isoformat('minutes')}/{self.interval_minutes}m"


@dataclass(frozen=True)
class Cadence:
    """The tiers, the window they span, and how a wake-up is matched to a slot."""

    tiers: tuple[CadenceTier, ...]
    end: time = SCAN_WINDOW_END
    # How many minutes late a wake-up may be and still claim its slot.
    #
    # MUST stay strictly below the cron's wake-up period (currently 5 minutes), or two
    # consecutive wake-ups can both claim the same slot and the pass runs twice. At 0 the
    # rule is exact-minute and has no coupling to the cron schedule at all; the cost is
    # that a wake-up delayed past its minute loses that slot. Statelessness bounds the
    # damage — the next slot recomputes the whole morning — so 0 is the safe default.
    grace_minutes: int = DEFAULT_GRACE_MINUTES

    @property
    def start(self) -> time:
        """When the window opens. The first tier's start, by construction."""
        return self.tiers[0].start

    def slots(self, day: datetime) -> list[datetime]:
        """Every scheduled scan moment on a given ET date, in order.

        Built by adding wall-clock minutes in ET, so a DST transition inside the window
        yields the correct number of runs rather than a UTC-arithmetic drift.

        The window's closing minute is always the last slot. The 09:25 pass is the
        authoritative one and is not the tiers' to remove.
        """
        et = to_et(day)

        def on(at: time) -> datetime:
            return et.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)

        end_at = on(self.end)
        moments: list[datetime] = []

        for index, tier in enumerate(self.tiers):
            tier_start = on(tier.start)
            # Each tier is sampled from its OWN start, so 04:15 with a 60-minute interval
            # is 04:15, 05:15, 06:15 — the discovery pass first, then hourly from it.
            tier_end = on(self.tiers[index + 1].start) if index + 1 < len(self.tiers) else end_at
            current = tier_start
            while current < tier_end and current <= end_at:
                moments.append(current)
                current += timedelta(minutes=tier.interval_minutes)

        if not moments or moments[-1] != end_at:
            moments.append(end_at)
        return moments

    def is_open(self, moment: datetime) -> bool:
        """Whether an ET moment falls inside the scan window, inclusive at both ends."""
        return self.start <= at_minute(moment).time() <= self.end

    def slot_for(self, moment: datetime) -> datetime | None:
        """The scheduled slot this wake-up claims, or None if it claims none.

        Compared at minute resolution, for the same reason the window bounds are: Render
        starts a job 10-45 s after its scheduled minute, so the 09:25 pass begins around
        09:25:10 and must still be the 09:25 slot.
        """
        et = at_minute(moment)
        if not self.is_open(et):
            return None
        claimable = [slot for slot in self.slots(et) if slot <= et]
        if not claimable:
            return None
        slot = claimable[-1]
        late_by = (et - slot).total_seconds() / 60
        return slot if late_by <= self.grace_minutes else None

    def next_slot_after(self, moment: datetime) -> datetime | None:
        """The next scheduled pass strictly after this moment, if the day has one left."""
        et = at_minute(moment)
        return next((slot for slot in self.slots(et) if slot > et), None)

    def is_scheduled(self, moment: datetime) -> bool:
        """Whether this wake-up should do real work."""
        return self.slot_for(moment) is not None

    def tier_for(self, moment: datetime) -> CadenceTier | None:
        """Which tier governs this moment, for logs and skip messages."""
        at = at_minute(moment).time()
        if not (self.start <= at <= self.end):
            return None
        return next((tier for tier in reversed(self.tiers) if tier.start <= at), None)

    def describe(self) -> str:
        """One line naming the window, the tiers and the pass count. For logs."""
        tiers = " ".join(tier.describe() for tier in self.tiers)
        return (
            f"{self.start.isoformat('minutes')}-{self.end.isoformat('minutes')} ET, "
            f"tiers {tiers} ({self.passes_per_session()} passes/session)"
        )

    def passes_per_session(self) -> int:
        """How many scans a session runs.

        Date-independent: the slots are built by adding wall-clock minutes in ET, so a
        DST transition day yields the same count as any other. `REFERENCE_DAY` is
        therefore an arbitrary weekday and not a `datetime.now()` in disguise — scanner
        logic never reads the wall clock.
        """
        return len(self.slots(REFERENCE_DAY))


def parse_cadence(
    spec: str, *, end: time = SCAN_WINDOW_END, grace_minutes: int = DEFAULT_GRACE_MINUTES
) -> Cadence:
    """Parse `"04:15/60,07:00/30"` into a `Cadence`, rejecting anything unhonourable.

    Every failure here is a deployment-time typo, so each one says what was wrong with
    the value rather than raising a bare parse error a long way from the cause.
    """
    tiers: list[CadenceTier] = []
    for chunk in (part.strip() for part in spec.split(",")):
        if not chunk:
            continue
        at, _, interval = chunk.partition("/")
        if not interval:
            raise CadenceError(
                f"Cadence tier {chunk!r} is missing its interval. Expected 'HH:MM/minutes', "
                f'e.g. "{DEFAULT_CADENCE_SPEC}".'
            )
        try:
            start = time.fromisoformat(at.strip())
        except ValueError as exc:
            raise CadenceError(f"Cadence tier {chunk!r} has an unreadable start time.") from exc
        try:
            minutes = int(interval.strip())
        except ValueError as exc:
            raise CadenceError(f"Cadence tier {chunk!r} has a non-numeric interval.") from exc
        if minutes <= 0:
            raise CadenceError(f"Cadence tier {chunk!r} must have a positive interval.")
        tiers.append(CadenceTier(start, minutes))

    if not tiers:
        raise CadenceError(
            f"No cadence tiers in {spec!r}. Expected 'HH:MM/minutes' entries, "
            f'e.g. "{DEFAULT_CADENCE_SPEC}".'
        )

    for earlier, later in zip(tiers, tiers[1:]):
        if later.start <= earlier.start:
            raise CadenceError(
                f"Cadence tiers must ascend: {later.start.isoformat('minutes')} does not come "
                f"after {earlier.start.isoformat('minutes')} in {spec!r}."
            )
    if tiers[-1].start >= end:
        raise CadenceError(
            f"The last cadence tier starts at {tiers[-1].start.isoformat('minutes')}, at or "
            f"after the window's close at {end.isoformat('minutes')}, so it would never run."
        )
    if grace_minutes < 0:
        raise CadenceError("Cadence grace cannot be negative.")

    return Cadence(tuple(tiers), end=end, grace_minutes=grace_minutes)


def load_cadence() -> Cadence:
    """The configured cadence, parsed and validated.

    **This is where a bad spec fails.** `app.config` cannot validate it with a field
    validator — importing this module from one initialises the scanner package, which
    reaches `core.database`, which reads settings at import time. So the check lives here,
    and every scanning entry point calls it before spending an FMP call or writing a row:
    `scripts/run_scan.py` at the top of `main()`, and `Scanner.__init__`.

    Settings are imported inside the function for the same reason, and so this module
    stays usable — and testable — without an environment.
    """
    from app.config import get_settings

    settings = get_settings()
    return parse_cadence(
        settings.scan_cadence_tiers, grace_minutes=settings.scan_cadence_grace_minutes
    )


def is_within_scan_window(moment: datetime, cadence: Cadence | None = None) -> bool:
    """Whether an ET moment falls in the configured pre-market scan window."""
    return (cadence or load_cadence()).is_open(moment)


def is_scheduled_pass(moment: datetime, cadence: Cadence | None = None) -> bool:
    """Whether this wake-up is one the tiered cadence wants to run."""
    return (cadence or load_cadence()).is_scheduled(moment)


def scan_times_for(day: datetime, cadence: Cadence | None = None) -> list[datetime]:
    """Every scheduled scan moment on a given ET date."""
    return (cadence or load_cadence()).slots(day)
