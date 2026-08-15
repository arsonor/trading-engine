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
   pass at 04:05 carries ~1 bar per ticker and a pass at 09:25 carries ~65: pass counts
   alone overstate what thinning the early hours saves. That curve is only populated for
   runs recorded after per-pass byte tracking shipped, so it fills in from the first
   market morning after that deploy and is reported as "no data" before then.

The Tiingo probe measured 04:16-05:12 and 08:38-09:29 and nothing in between, which is
exactly where the proposed 07:00 and 08:00 boundaries sit. This closes that hole with
data the scanner has been collecting all along.
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


@dataclass
class Bucket:
    """Every pass recorded at one ET clock time, across all sessions."""

    passes: int = 0
    sessions: set[date] = field(default_factory=set)
    stage_2: list[int] = field(default_factory=list)
    survivors: list[int] = field(default_factory=list)
    bytes_used: list[int] = field(default_factory=list)

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


def _as_of(run: ScanRun) -> datetime | None:
    """The ET moment the pass decided on, as stamped by the pipeline."""
    raw = (run.stage_counts_json or {}).get("as_of_et")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


async def profile_cadence(since: date | None, csv_path: str | None) -> int:
    async with async_session_maker() as db:
        stmt = select(ScanRun).where(ScanRun.status == ScanRunStatus.COMPLETED)
        rows = (await db.execute(stmt.order_by(ScanRun.started_at))).scalars().all()

    buckets: dict[str, Bucket] = defaultdict(Bucket)
    sessions: set[date] = set()
    skipped_undated = 0

    for run in rows:
        as_of = _as_of(run)
        if as_of is None:
            skipped_undated += 1
            continue
        if since is not None and as_of.date() < since:
            continue

        counts = (run.stage_counts_json or {}).get("counts") or {}
        bucket = buckets[as_of.strftime("%H:%M")]
        bucket.passes += 1
        bucket.sessions.add(as_of.date())
        bucket.stage_2.append(int(counts.get(STAGE_2_KEY) or 0))
        bucket.survivors.append(int(counts.get(RISK_KEY) or counts.get(STAGE_3_KEY) or 0))
        # Absent on every run recorded before per-pass byte tracking shipped. Left out
        # rather than counted as zero — "not measured" and "cost nothing" are different.
        measured_bytes = (run.stage_counts_json or {}).get("bytes_used")
        if isinstance(measured_bytes, int):
            bucket.bytes_used.append(measured_bytes)
        sessions.add(as_of.date())

    if not buckets:
        print("No completed scan_runs with an ET stamp were found.")
        if skipped_undated:
            print(f"  ({skipped_undated} run(s) had no as_of_et and were ignored.)")
        return 1

    print(f"\n{len(sessions)} session(s), {sum(b.passes for b in buckets.values())} completed pass(es)")
    print(f"Sessions: {', '.join(sorted(s.isoformat() for s in sessions))}\n")

    header = f"{'ET':>6}  {'passes':>6}  {'stage2 mean':>11}  {'productive':>10}  {'survivors':>9}  {'MB/pass':>7}"
    print(header)
    print("-" * len(header))

    for clock in sorted(buckets):
        b = buckets[clock]
        productive = f"{b.productive_passes}/{b.passes}"
        megabytes = f"{b.mean_bytes / 1_000_000:.2f}" if b.bytes_used else "  --"
        print(
            f"{clock:>6}  {b.passes:>6}  {b.mean_stage_2:>11.2f}  {productive:>10}  "
            f"{b.mean_survivors:>9.2f}  {megabytes:>7}"
        )

    measured = sum(len(b.bytes_used) for b in buckets.values())
    if not measured:
        print(
            "\nNo per-pass byte figures yet: those are recorded from the first market "
            "morning after byte tracking deploys. The stage columns above are complete."
        )

    _print_first_productive(buckets)

    if csv_path:
        _write_csv(csv_path, buckets)
        print(f"\nWrote {csv_path}")

    return 0


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
            ["et", "passes", "stage_2_mean", "productive_passes", "survivors_mean", "bytes_mean"]
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
                    round(b.mean_bytes, 1) if b.bytes_used else "",
                ]
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Profile candidate yield and cost by time of day, from stored scan_runs."
    )
    parser.add_argument("--since", help="Only sessions on or after this date (YYYY-MM-DD).")
    parser.add_argument("--csv", help="Also write the table to this CSV path.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)

    raise SystemExit(
        run_cli(
            profile_cadence(
                date.fromisoformat(args.since) if args.since else None,
                args.csv,
            )
        )
    )
