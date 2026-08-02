"""Run the pre-market scanner.

Output goes to stdout and logs only — alert persistence and broadcast are Phase 3.

    uv run python scripts/run_scan.py --fixture --profile demo --at "2026-07-28 08:45 ET"
    uv run python scripts/run_scan.py --fixture --profile production --at "2026-07-28 09:25"
    uv run python scripts/run_scan.py --fixture --profile demo --dry-run --verbose

V1 has no live pre-market data, so `--fixture` is required: the free tier has neither
real-time quotes nor intraday bars. The scenario file supplies Stage 2's inputs while
Stages 1 and 3 run on real reference data.
"""

import argparse
import sys

# Import first: puts the backend directory on sys.path for the `app.*` imports below.
from _bootstrap import configure_logging, run_cli

from app.config import get_settings
from app.models.scan_run import ScanRunStatus
from app.services.alerts import ScannerAlertService
from app.services.scanner.candidate import STAGE_2, STAGE_3, STAGE_RISK
from app.services.scanner.clock import FixedClock, SystemClock, describe, parse_scan_time
from app.services.scanner.pipeline import Scanner, ScanResult
from app.services.scanner.profiles import available_profiles
from app.services.scanner.rvol import get_rvol_calculator
from app.services.scanner.settings_store import ScannerSettingsStore
from app.services.scanner.snapshot import FixtureSnapshotProvider

DEMO_BANNER = "!" * 78


def _wrap(text: str, width: int = 74) -> list[str]:
    """Wrap a long diagnostic so it stays readable in a terminal."""
    import textwrap

    return textwrap.wrap(text, width=width)


def _print_header(scanner: Scanner, provider, clock, args) -> None:
    profile = scanner.profile
    print()
    if profile.is_demo:
        print(DEMO_BANNER)
        print("  DEMO PROFILE — thresholds are loosened so the pipeline can be seen")
        print("  running on free-tier data. These candidates are ILLUSTRATIVE and must")
        print("  NOT be treated as real trading signals.")
        # The EFFECTIVE cap, after any stored override. Printing the designed value here
        # is what previously let the banner contradict the stage logs in the same run.
        print(f"  Effective float cap: < {profile.float_max:,}")
        print(DEMO_BANNER)

    print("Pre-market scan")
    print("=" * 78)
    print(f"  Scan time        : {describe(clock.now_et())}")
    print(f"  Profile          : {profile.name}" + ("  [DEMO]" if profile.is_demo else ""))
    # Both derived from the profile's effective fields, so the banner above, this
    # header and the stage logs can never disagree.
    print(f"  Thresholds       : {profile.threshold_summary()}")
    print(f"  Risk filters     : {profile.risk_summary()}")
    print(f"  Snapshot source  : {provider.source} ({getattr(provider, 'name', 'n/a')})")
    print(f"  RVOL mode        : {get_settings().rvol_mode}")
    if args.dry_run:
        print("  Dry run          : no scan_runs row will be written")


def _print_result(result: ScanResult, verbose: bool) -> None:
    counts = result.counts

    print()
    print("Stage funnel")
    print("-" * 78)
    print(f"  Universe considered      : {counts.universe}")
    print(f"  Stage 1 (liquidity)      : {counts.stage_1}")
    print(f"  Stage 2 (gap + rvol)     : {counts.stage_2}")
    print(f"  Stage 3 (room to run)    : {counts.stage_3}")
    print(f"  Risk filters passed      : {counts.risk_passed}")

    if result.status == ScanRunStatus.FAILED:
        print()
        print("  SCAN FAILED — this is an outage, not a quiet market.")
        print(f"  {result.error}")
        return

    if result.status == ScanRunStatus.SKIPPED:
        print()
        print(f"  SCAN SKIPPED — {result.error}")
        return

    print()
    if result.candidates:
        print(f"Candidates ({len(result.candidates)}) — sorted by upside")
        print("-" * 78)
        header = f"  {'ticker':<8}{'gap%':>8}{'rvol%':>10}{'price':>10}{'resist':>10}{'upside%':>9}  source"
        print(header)
        for c in result.candidates:
            print(
                f"  {c.ticker:<8}{c.gap_pct:>8.2f}{c.rvol_pct:>10.2f}"
                f"{c.price_premarket_current:>10.2f}{c.nearest_resistance:>10.2f}"
                f"{c.upside_pct:>9.2f}  {c.resistance_source}"
            )
        if any(c.rvol_is_approximate for c in result.candidates):
            print()
            print("  NOTE: RVOL is APPROXIMATE (not time-of-day normalized) — needs FMP")
            print("        Premium extended-hours bars (app V3).")
    elif result.misconfiguration:
        # An empty result caused by broken thresholds is not evidence about the market,
        # so it must not be reported as one.
        print("Candidates: none — but this looks like a MISCONFIGURATION.")
        print("-" * 78)
        for line in _wrap(result.misconfiguration):
            print(f"  {line}")
    else:
        print("Candidates: none.")
        print("  The scan COMPLETED successfully and found nothing. This is a quiet")
        print("  market, not a broken scanner.")

    if result.tape and not result.tape.is_available:
        print()
        print(f"  Market tape: not measured — {result.tape.detail}")

    if verbose and result.rejections:
        print()
        print("Rejections")
        print("-" * 78)
        for stage in (STAGE_2, STAGE_3, STAGE_RISK):
            stage_rejections = result.rejections_at(stage)
            if not stage_rejections:
                continue
            print(f"  {stage} ({len(stage_rejections)}):")
            for rejection in stage_rejections:
                print(f"    {rejection.ticker:<8} {rejection.reason:<28} {rejection.detail}")
    elif result.rejections:
        print()
        by_reason: dict[str, int] = {}
        for rejection in result.rejections:
            by_reason[rejection.reason] = by_reason.get(rejection.reason, 0) + 1
        print("Rejection reasons (use --verbose for per-ticker detail)")
        print("-" * 78)
        for reason, count in sorted(by_reason.items(), key=lambda kv: -kv[1]):
            print(f"  {count:>4}  {reason}")

    print()
    print(f"  Status           : {result.status}")
    print(f"  Final pass (09:25): {result.is_final_pass}")
    print(f"  Duration         : {result.duration_s:.2f}s")
    if result.scan_run_id:
        print(f"  scan_runs.id     : {result.scan_run_id}")


async def main(args: argparse.Namespace) -> int:
    # Resolve through the settings store, not get_profile(), so the layering holds:
    # env defaults -> stored overrides (edited in Settings) -> explicit --profile.
    # Calling get_profile() here would silently ignore every saved threshold edit.
    try:
        profile = await ScannerSettingsStore().resolve_profile(args.profile)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    if not args.fixture:
        print(
            "Error: V1 has no live pre-market data source (FMP free tier has no real-time\n"
            "quotes and no intraday bars). Re-run with --fixture."
        )
        return 1

    scenario_path = args.snapshot_file or get_settings().scan_snapshot_fixture
    try:
        provider = FixtureSnapshotProvider(scenario_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1

    if args.at:
        try:
            clock = FixedClock(parse_scan_time(args.at))
        except ValueError as exc:
            print(f"Error: {exc}")
            return 1
    elif provider.declared_as_of is not None:
        clock = FixedClock(provider.declared_as_of)
    else:
        clock = SystemClock()

    scanner = Scanner(
        snapshot_provider=provider,
        profile=profile,
        clock=clock,
        rvol_calculator=get_rvol_calculator(),
    )

    _print_header(scanner, provider, clock, args)

    result = await scanner.run(
        tickers=[t.strip().upper() for t in args.tickers.split(",")] if args.tickers else None,
        dry_run=args.dry_run,
        ignore_window=args.ignore_window,
    )
    _print_result(result, args.verbose)

    # Persist + broadcast unless this is a dry run or --no-persist was passed.
    if not args.dry_run and not args.no_persist and result.succeeded:
        report = await ScannerAlertService().persist_scan_result(result)
        print()
        print("Alert delivery")
        print("-" * 78)
        print(f"  Created          : {len(report.created)}  {', '.join(report.created) or '-'}")
        print(f"  Updated in place : {len(report.updated)}  {', '.join(report.updated) or '-'}")
        print(f"  Broadcast        : {report.broadcast} alert(s) on the 'alerts' channel")
        print(f"  Session          : {report.session_date}")

    if result.status == ScanRunStatus.FAILED:
        return 2
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the pre-market scanner.")
    parser.add_argument(
        "--fixture", action="store_true", help="Use recorded snapshots (required in V1)"
    )
    parser.add_argument("--snapshot-file", help="Path to a snapshot scenario JSON file")
    parser.add_argument(
        "--profile",
        default=None,
        help=f"Threshold profile: {' | '.join(available_profiles())} (default: SCAN_PROFILE)",
    )
    parser.add_argument("--at", help='Scan moment in ET, e.g. "2026-07-28 08:45 ET"')
    parser.add_argument("--tickers", help="Restrict the scan to these tickers")
    parser.add_argument(
        "--dry-run", action="store_true", help="Do not write a scan_runs row or persist alerts"
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Run and record the scan, but do not persist or broadcast alerts",
    )
    parser.add_argument(
        "--ignore-window",
        action="store_true",
        help="Scan even outside 04:00-09:25 ET (manual testing only)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Per-ticker rejections")
    args = parser.parse_args()
    configure_logging(args.verbose)
    sys.exit(run_cli(main(args)))
