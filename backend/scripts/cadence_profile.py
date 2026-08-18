"""Where does the pre-market session actually wake up? Read it out of `scan_runs`.

    uv run python scripts/cadence_profile.py
    uv run python scripts/cadence_profile.py --since 2026-08-10
    uv run python scripts/cadence_profile.py --csv cadence.csv

**Read-only.** It runs SELECTs against `scan_runs` and writes nothing.

The tiered-cadence follow-up proposes scanning coarsely early and finely late, and the
argument for it rests on two curves:

1. **When candidates appear.** Every completed pass since the observation window stored
   its ET moment and its stage counts, so this is already answerable — no new fetching,
   no waiting for a market day. That curve decides where the tier boundaries go.

2. **What each pass costs in bytes.** The fan-out asks for the day's 5-minute bars, so a
   pass at 04:05 carries ~1 bar per ticker and a pass at 09:25 carries up to ~65 (~20 in
   practice, since most Stage-1 names print sparsely in pre-market): pass counts alone
   overstate what thinning the early hours saves. That curve is only populated for
   runs recorded after per-pass byte tracking shipped, so it fills in from the first
   market morning after that deploy and is reported as "no data" before then.

Once that second curve exists, the script also reports the session's bandwidth under the
old uniform cadence and under the configured tiers. That comparison is a **measurement,
not a projection**: a pass's size is a function of its clock time alone, so summing the
measured curve over a different set of clock times is arithmetic over the same numbers.
See `_print_bandwidth`.

The Tiingo probe measured 04:16-05:12 and 08:38-09:29 and nothing in between, which is
exactly where the proposed 07:00 and 08:00 boundaries sit. This closes that hole with
data the scanner has been collecting all along.

**Yield is not the deciding number, churn is.** Scans are stateless and alerts dedup per
(ticker, session), so a pass only earns its place if it surfaces a ticker the *next* pass
would not have surfaced anyway. A run of passes all reporting 20 candidates is one
candidate set being re-reported, not twenty passes' worth of information. So this also
reports, per clock time, how many tickers appear for the FIRST time in that pass — and
how many of those were still candidates at the session's final pass, which is the only
sighting that reaches the user as a confirmed candidate.

Simulated and fixture runs are excluded by default (`snapshot_source`): `--at` reruns
during development land in `scan_runs` next to real passes and will otherwise skew any
clock time they happen to cluster on.
"""

import argparse
import csv
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

# Import first: puts the backend directory on sys.path for the `app.*` imports below.
from _bootstrap import configure_logging, run_cli
from sqlalchemy import select

from app.core.database import async_session_maker
from app.models.scan_run import ScanRun, ScanRunStatus

# Stage 2 is the interesting one: it is the first stage that reacts to the morning's
# actual trading (gap + RVOL), so its survivor count is what "the market woke up" means.
STAGE_2_KEY = "stage_2_momentum"
STAGE_3_KEY = "stage_3_room_to_run"
RISK_KEY = "risk_filters"

# `--at` reruns against fixtures write real `scan_runs` rows. They are development
# artefacts, not passes the market ever saw, and they cluster on whatever clock time was
# convenient that afternoon.
SOURCE_LIVE = "fmp-live"


def _candidates(run: ScanRun) -> set[str]:
    """The tickers this pass surfaced, as stored on the run."""
    tickers = (run.stage_counts_json or {}).get("candidates")
    return {t for t in tickers if isinstance(t, str)} if isinstance(tickers, list) else set()


@dataclass
class Bucket:
    """Every pass recorded at one ET clock time, across all sessions."""

    passes: int = 0
    sessions: set[date] = field(default_factory=set)
    stage_2: list[int] = field(default_factory=list)
    survivors: list[int] = field(default_factory=list)
    bytes_used: list[int] = field(default_factory=list)
    calls_used: list[int] = field(default_factory=list)
    # Tickers seen for the first time in this pass, and how many of those were still
    # candidates at the session's final pass. The second number is the one that says
    # whether an early sighting ever reached the user as a confirmed candidate.
    first_seen: list[int] = field(default_factory=list)
    first_seen_confirmed: list[int] = field(default_factory=list)

    @property
    def mean_first_seen(self) -> float:
        return sum(self.first_seen) / len(self.first_seen) if self.first_seen else 0.0

    @property
    def total_first_seen(self) -> int:
        return sum(self.first_seen)

    @property
    def total_first_seen_confirmed(self) -> int:
        return sum(self.first_seen_confirmed)

    @property
    def mean_stage_2(self) -> float:
        return sum(self.stage_2) / len(self.stage_2) if self.stage_2 else 0.0

    @property
    def mean_survivors(self) -> float:
        return sum(self.survivors) / len(self.survivors) if self.survivors else 0.0

    @property
    def productive_passes(self) -> int:
        """Passes where Stage 2 found anything at all — the honest test of "worth running"."""
        return sum(1 for n in self.stage_2 if n > 0)

    @property
    def mean_bytes(self) -> float:
        return sum(self.bytes_used) / len(self.bytes_used) if self.bytes_used else 0.0

    @property
    def mean_calls(self) -> float:
        return sum(self.calls_used) / len(self.calls_used) if self.calls_used else 0.0

    @property
    def bytes_per_call(self) -> float:
        """Mean payload size — the number that reconciles this table with 4C's figure.

        4C reported "672 calls, 10.2 MB" for one full live pass, a ~15 KB mean payload,
        and the ~47%-of-allowance projection was built on it. The measured curve says a
        09:25 pass costs ~1.7 MB, roughly six times less, so one of the two inputs moved
        and this pair of columns is what says which. **Measured 18 August 2026 over seven
        sessions: 737 calls a pass, against 4C's 672.** The Stage-1 set has GROWN ~10%, so
        the call count explains none of the gap and the payload explains all of it:

        * 4C's replay: 10.2 MB / 672 = **15.2 KB** a call.
        * A live 09:25 pass: 1.67 MB / 737 = **2.27 KB** a call — a **6.7x** difference,
          slightly wider than the MB figures alone suggest, because it carries 10% more
          tickers than the pass it is being compared with.

        The mechanism is the `--at` replay, but read it as *coverage*, not window length.
        For a PAST session the intraday endpoint returns the whole extended day (04:00-20:00)
        INCLUDING regular hours, when every ticker prints a bar every five minutes; in
        pre-market most Stage-1 small caps print sparsely. At ~110 bytes a bar that is
        ~138 bars a ticker in the replay against ~20 at a live 09:25 — not the ~65 the clock
        allows. So "190 bars against 65" is the right direction but only ~2.9x of the
        measured 6.7x: it understates the correction, and is not a formula to predict with.

        Either way the percentage saving from thinning the cadence is unaffected, because
        both curves scale with the same Stage-1 count.
        """
        calls = sum(self.calls_used)
        return sum(self.bytes_used) / calls if calls and self.bytes_used else 0.0


def _as_of(run: ScanRun) -> datetime | None:
    """The ET moment the pass decided on, as stamped by the pipeline."""
    raw = (run.stage_counts_json or {}).get("as_of_et")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


async def profile_cadence(
    since: date | None, csv_path: str | None, include_simulated: bool
) -> int:
    async with async_session_maker() as db:
        stmt = select(ScanRun).where(ScanRun.status == ScanRunStatus.COMPLETED)
        rows = (await db.execute(stmt.order_by(ScanRun.started_at))).scalars().all()

    # One ordered timeline per session, so "first seen" means first in that morning.
    timeline: dict[date, list[tuple[datetime, ScanRun]]] = defaultdict(list)
    skipped_undated = 0
    skipped_simulated = 0

    for run in rows:
        as_of = _as_of(run)
        if as_of is None:
            skipped_undated += 1
            continue
        if since is not None and as_of.date() < since:
            continue
        source = (run.stage_counts_json or {}).get("snapshot_source")
        if not include_simulated and source != SOURCE_LIVE:
            skipped_simulated += 1
            continue
        timeline[as_of.date()].append((as_of, run))

    buckets: dict[str, Bucket] = defaultdict(Bucket)
    sessions: set[date] = set()

    for session_date, passes in timeline.items():
        passes.sort(key=lambda pair: pair[0])
        sessions.add(session_date)
        confirmed = _candidates(passes[-1][1]) if passes else set()
        seen_so_far: set[str] = set()

        for as_of, run in passes:
            counts = (run.stage_counts_json or {}).get("counts") or {}
            bucket = buckets[as_of.strftime("%H:%M")]
            bucket.passes += 1
            bucket.sessions.add(session_date)
            bucket.stage_2.append(int(counts.get(STAGE_2_KEY) or 0))
            bucket.survivors.append(int(counts.get(RISK_KEY) or counts.get(STAGE_3_KEY) or 0))
            # Absent on every run recorded before per-pass byte tracking shipped. Left
            # out rather than counted as zero — "not measured" and "cost nothing" are
            # different claims.
            measured_bytes = (run.stage_counts_json or {}).get("bytes_used")
            if isinstance(measured_bytes, int):
                bucket.bytes_used.append(measured_bytes)
                # Collected only alongside a byte figure, so the two lists stay aligned
                # and bytes-per-call is a ratio of the same passes. `api_calls_used` has
                # existed since the v2 schema and was written as 0 by every run recorded
                # before per-pass tracking shipped — averaging those in would halve the
                # payload size and invent a reconciliation that is not there.
                bucket.calls_used.append(run.api_calls_used or 0)

            fresh = _candidates(run) - seen_so_far
            bucket.first_seen.append(len(fresh))
            bucket.first_seen_confirmed.append(len(fresh & confirmed))
            seen_so_far |= _candidates(run)

    if not buckets:
        print("No completed scan_runs with an ET stamp were found.")
        if skipped_undated:
            print(f"  ({skipped_undated} run(s) had no as_of_et and were ignored.)")
        if skipped_simulated:
            print(f"  ({skipped_simulated} simulated run(s) excluded; --include-simulated keeps them.)")
        return 1

    print(f"\n{len(sessions)} session(s), {sum(b.passes for b in buckets.values())} completed pass(es)")
    print(f"Sessions: {', '.join(sorted(s.isoformat() for s in sessions))}\n")

    header = (
        f"{'ET':>6}  {'passes':>6}  {'stage2':>7}  {'survivors':>9}  "
        f"{'new':>5}  {'new kept':>8}  {'calls':>6}  {'MB/pass':>7}"
    )
    print(header)
    print("-" * len(header))

    for clock in sorted(buckets):
        b = buckets[clock]
        megabytes = f"{b.mean_bytes / 1_000_000:.2f}" if b.bytes_used else "  --"
        calls = f"{b.mean_calls:.0f}" if b.calls_used else "--"
        kept = f"{b.total_first_seen_confirmed}/{b.total_first_seen}"
        print(
            f"{clock:>6}  {b.passes:>6}  {b.mean_stage_2:>7.2f}  {b.mean_survivors:>9.2f}  "
            f"{b.mean_first_seen:>5.2f}  {kept:>8}  {calls:>6}  {megabytes:>7}"
        )

    print(
        "\nnew      = tickers surfaced for the FIRST time in that pass, per pass\n"
        "new kept = how many of those were still candidates at the session's final pass\n"
        "calls    = FMP calls that pass made; with MB/pass it gives the mean payload size"
    )

    measured = sum(len(b.bytes_used) for b in buckets.values())
    if not measured:
        print(
            "\nNo per-pass byte figures yet: those are recorded from the first market "
            "morning after byte tracking deploys. The stage columns above are complete."
        )
    else:
        _print_bandwidth(buckets)

    _print_first_productive(buckets)

    if csv_path:
        _write_csv(csv_path, buckets)
        print(f"\nWrote {csv_path}")

    return 0


def _on_the_five_minute_grid(buckets: dict[str, Bucket]) -> dict[str, float]:
    """Mean bytes per scheduled slot, keyed to the 5-minute grid the cron fires on.

    A pass that began at 05:06 is the 05:05 wake-up arriving a minute late, not a slot of
    its own — Render's own lateness plus a minute. Left ungrouped it would be counted as a
    67th pass while 05:05 looked unmeasured, which would overstate the old cadence's total
    and understate the new one's coverage. The gate truncates to the minute for the same
    class of reason; this truncates to the slot.
    """
    grouped: dict[str, list[float]] = defaultdict(list)
    for clock, bucket in buckets.items():
        if not bucket.bytes_used:
            continue
        hour, minute = (int(part) for part in clock.split(":"))
        grouped[f"{hour:02d}:{minute - minute % 5:02d}"].append(bucket.mean_bytes)
    return {slot: sum(values) / len(values) for slot, values in grouped.items()}


def _print_bandwidth(buckets: dict[str, Bucket]) -> None:
    """Measured session bandwidth under the old cadence and under the configured one.

    **This is a measurement, not a projection, and the reason is worth stating.** A pass's
    cost is a function of its clock time and nothing else: the fan-out asks for the day's
    5-minute bars from 04:00 to now, so a 05:15 pass carries ~15 bars per ticker whether
    or not a 05:10 pass ran. Scans are stateless. So summing the measured per-pass curve
    over a different set of clock times gives what that cadence WOULD have cost on the
    same mornings — the same arithmetic, over a subset of the same numbers.

    Two caveats it would be dishonest to leave out:

    * Only clock times with a measured figure contribute. A tier boundary landing on a
      minute no pass has sampled yet would be missing, and is reported as such.
    * The `--at` replays that produced 4C's 10.2 MB figure are excluded from this table
      entirely (`snapshot_source`), so the two numbers are not comparable. See
      `Bucket.bytes_per_call`.
    """
    from app.services.scanner.cadence import load_cadence

    measured = _on_the_five_minute_grid(buckets)
    cadence = load_cadence()
    scheduled = {slot.strftime("%H:%M") for slot in cadence.slots(datetime(2026, 7, 28))}

    before = sum(measured.values())
    after = sum(mb for clock, mb in measured.items() if clock in scheduled)
    missing = sorted(scheduled - set(measured))

    print("\nBandwidth — measured per-pass bytes, summed over each cadence")
    print("-" * 60)
    print(f"  {'every 5 min (as measured)':<34}{len(measured):>4} passes  {before / 1e6:>8.1f} MB")
    print(f"  {'configured tiers':<34}{len(scheduled & set(measured)):>4} passes  {after / 1e6:>8.1f} MB")
    if before:
        print(f"  {'saving':<34}{'':>11}  {100 * (1 - after / before):>7.1f}%")

    # Against the allowance, which is the only figure that decides anything. 21 trading
    # days is the conventional month used everywhere else in this project's budgeting.
    from app.config import get_settings

    allowance_gb = get_settings().fmp_monthly_bandwidth_gb
    for label, total in (("every 5 min", before), ("configured tiers", after)):
        monthly_gb = total * 21 / 1e9
        print(
            f"  {label:<34}{monthly_gb:>8.2f} GB/month live "
            f"({100 * monthly_gb / allowance_gb:.1f}% of {allowance_gb:.0f} GB)"
        )

    if missing:
        print(
            f"\n  NOTE: {len(missing)} scheduled clock time(s) have no measured pass yet "
            f"({', '.join(missing)}), so the tiered figure is a floor, not a total."
        )
    print(
        "\n  Not a projection: a pass's size depends on its clock time alone (the fan-out\n"
        "  asks for every bar since 04:00), so this is the measured curve re-summed over\n"
        "  the passes each cadence keeps. The saving is smaller than the pass count\n"
        "  suggests — the passes kept are the late, expensive ones — and the percentage\n"
        "  holds at any universe size, since both totals scale with the Stage-1 count."
    )


def _print_first_productive(buckets: dict[str, Bucket]) -> None:
    """The single number the cadence boundaries hang off."""
    productive = [clock for clock in sorted(buckets) if buckets[clock].productive_passes]
    if not productive:
        print("\nNo pass in this range produced a Stage 2 survivor.")
        return

    print(
        f"\nEarliest pass that ever produced a Stage 2 survivor: {productive[0]}"
        f"\nEarliest pass productive in EVERY session: "
        f"{next((c for c in productive if buckets[c].productive_passes == buckets[c].passes), 'none')}"
    )
    print(
        "\nRead the boundaries off the columns above: a clock time whose passes are "
        "almost never productive is one to sample coarsely."
    )


def _write_csv(path: str, buckets: dict[str, Bucket]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "et",
                "passes",
                "stage_2_mean",
                "productive_passes",
                "survivors_mean",
                "first_seen",
                "first_seen_confirmed",
                "bytes_mean",
                "calls_mean",
                "bytes_per_call",
            ]
        )
        for clock in sorted(buckets):
            b = buckets[clock]
            writer.writerow(
                [
                    clock,
                    b.passes,
                    round(b.mean_stage_2, 3),
                    b.productive_passes,
                    round(b.mean_survivors, 3),
                    b.total_first_seen,
                    b.total_first_seen_confirmed,
                    round(b.mean_bytes, 1) if b.bytes_used else "",
                    round(b.mean_calls, 1) if b.calls_used else "",
                    round(b.bytes_per_call, 1) if b.calls_used else "",
                ]
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Profile candidate yield and cost by time of day, from stored scan_runs."
    )
    parser.add_argument("--since", help="Only sessions on or after this date (YYYY-MM-DD).")
    parser.add_argument("--csv", help="Also write the table to this CSV path.")
    parser.add_argument(
        "--include-simulated",
        action="store_true",
        help="Keep fixture/--at reruns. They are development artefacts, not real passes.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)

    raise SystemExit(
        run_cli(
            profile_cadence(
                date.fromisoformat(args.since) if args.since else None,
                args.csv,
                args.include_simulated,
            )
        )
    )
