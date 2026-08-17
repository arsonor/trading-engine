"""Run the pre-market scanner.

Output goes to stdout and logs only — alert persistence and broadcast are Phase 3.

    uv run python scripts/run_scan.py --fixture --profile demo --at "2026-07-28 08:45 ET"
    uv run python scripts/run_scan.py --fixture --profile production --at "2026-07-28 09:25"
    uv run python scripts/run_scan.py --fixture --profile demo --dry-run --verbose

**Live is the default since Phase 4C.** Stage 2 reads `extended=true` pre-market bars, one
call per Stage-1 candidate, summed over bars old enough to have settled.

`--fixture` remains first-class and is not deprecated: it is how the pipeline is exercised
offline, how CI stays free of live FMP, and how the demo profile is demonstrated. The
scenario file supplies Stage 2's inputs while Stages 1 and 3 run on real reference data.

`--at` works against past sessions too, which is the cheapest way to exercise the live path
outside pre-market hours: extended-hours history goes back to at least 2016.

**The cadence is tiered since Follow-up A**, so a wake-up inside the window is not
automatically a scan: 04:15 then hourly to 07:00, then 30/15/5 minutes, 19 passes a
session (`SCAN_CADENCE_TIERS`). `--at "2026-07-28 05:40"` is skipped as off-cadence, which
is what production would do at that minute; `--ignore-window` overrides both gates.
"""

import argparse
import sys

# Import first: puts the backend directory on sys.path for the `app.*` imports below.
from _bootstrap import configure_logging, run_cli

from app.config import get_settings
from app.models.scan_run import ScanRunStatus
from app.services.alerts import ScannerAlertService
from app.services.scanner.cadence import load_cadence
from app.services.scanner.candidate import STAGE_2, STAGE_3, STAGE_RISK
from app.services.scanner.clock import FixedClock, SystemClock, describe, parse_scan_time
from app.services.scanner.pipeline import (
    MODE_LIVE,
    SKIP_OFF_CADENCE,
    Scanner,
    ScanResult,
    describe_mode,
    resolve_mode,
)
from app.services.scanner.profiles import available_profiles
from app.services.scanner.rvol import get_rvol_calculator
from app.services.scanner.settings_store import ScannerSettingsStore
from app.services.scanner.snapshot import FixtureSnapshotProvider, FmpLiveSnapshotProvider

DEMO_BANNER = "!" * 78


def _wrap(text: str, width: int = 74) -> list[str]:
    """Wrap a long diagnostic so it stays readable in a terminal."""
    import textwrap

    return textwrap.wrap(text, width=width)


def _print_header(scanner: Scanner, provider, clock, args, mode: str, cadence) -> None:
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
    print(f"  Mode             : {describe_mode(mode)}")
    # Printed on every run because the cadence is now the reason a wake-up may do nothing,
    # and "which pass am I?" is the first question when a scan reports no work.
    print(f"  Cadence          : {cadence.describe()}")
    slot = cadence.slot_for(clock.now_et())
    scheduled = f"yes ({slot.strftime('%H:%M')} slot)" if slot else "NO — off-cadence wake-up"
    print(f"  Scheduled pass   : {scheduled}")


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
        if result.skip_reason == SKIP_OFF_CADENCE:
            print("  This is the tiered cadence working, not a fault. To scan an")
            print("  off-cadence minute anyway (local testing), pass --ignore-window.")
        # The row id is printed here too: a skipped wake-up now RECORDS itself, and an
        # operator reading this output should be able to go and find that row.
        if result.scan_run_id:
            print(f"  Recorded as scan_runs.id = {result.scan_run_id} (status=skipped)")
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

    if result.tape:
        print()
        label = result.tape.state if result.tape.is_available else "not measured"
        print(f"  Market tape: {label} — {result.tape.detail}")

    # Integrity findings are printed even on a clean run's failure modes, because the whole
    # point of a guard is that nobody goes looking for it. A split-distorted ticker shows
    # up as the BEST-looking row in the candidate table; it has to be contradicted in the
    # same output, not in a log file somebody reads afterwards.
    if result.integrity_warnings:
        print()
        print(f"DATA INTEGRITY — {len(result.integrity_warnings)} finding(s)")
        print("-" * 78)
        for warning in result.integrity_warnings:
            for i, line in enumerate(_wrap(warning)):
                print(f"  {line}" if i == 0 else f"    {line}")

    if result.data_quality_rejections:
        print()
        print(f"DATA QUALITY — {result.data_quality_suppressed} candidate(s) suppressed")
        print("-" * 78)
        print("  These cleared every stage but their reference data could not be trusted,")
        print("  so they were vetoed rather than shown. Upside sorts the candidate list, so")
        print("  an implausible one would otherwise appear FIRST.")
        for rejection in result.data_quality_rejections:
            print(f"  {rejection.ticker:<8} {rejection.reason}")
            for line in _wrap(rejection.detail, width=68):
                print(f"      {line}")

    if result.snapshot_failures:
        print()
        print(f"  Snapshot failures: {len(result.snapshot_failures)} ticker(s) could not "
              f"be fetched and were skipped")
        for ticker, why in sorted(result.snapshot_failures.items())[:5]:
            print(f"    {ticker:<8} {why[:60]}")
    if result.not_trading:
        print(f"  Not trading yet  : {len(result.not_trading)} ticker(s) had no settled "
              f"pre-market bars")

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

    # Live is the default since Phase 4C; `--fixture` is how the pipeline is exercised
    # offline and how the demo profile is demonstrated, so it stays first-class.
    if args.fixture:
        scenario_path = args.snapshot_file or get_settings().scan_snapshot_fixture
        try:
            provider = FixtureSnapshotProvider(scenario_path)
        except (FileNotFoundError, ValueError) as exc:
            print(f"Error: {exc}")
            return 1
    else:
        provider = FmpLiveSnapshotProvider()

    if args.at:
        try:
            clock = FixedClock(parse_scan_time(args.at))
        except ValueError as exc:
            print(f"Error: {exc}")
            return 1
    elif getattr(provider, "declared_as_of", None) is not None:
        clock = FixedClock(provider.declared_as_of)
    else:
        clock = SystemClock()

    # Live scans read a real index proxy; fixture replay stays offline and neutral.
    from app.services.scanner.risk import FmpMarketTape, NeutralMarketTape

    cadence = load_cadence()
    scanner = Scanner(
        tape_provider=NeutralMarketTape() if args.fixture else FmpMarketTape(),
        snapshot_provider=provider,
        profile=profile,
        clock=clock,
        rvol_calculator=get_rvol_calculator(),
        cadence=cadence,
    )

    # `--no-persist` is the deprecated spelling; honour it so existing invocations keep
    # working rather than silently switching to live mode.
    no_alerts = args.no_alerts or args.no_persist
    mode = resolve_mode(args.dry_run, no_alerts)
    if args.no_persist and not args.no_alerts:
        print("  NOTE: --no-persist is deprecated; use --no-alerts (same behaviour).")

    _print_header(scanner, provider, clock, args, mode, cadence)

    result = await scanner.run(
        tickers=[t.strip().upper() for t in args.tickers.split(",")] if args.tickers else None,
        dry_run=args.dry_run,
        no_alerts=no_alerts,
        ignore_window=args.ignore_window,
    )
    _print_result(result, args.verbose)

    # Alerts are written only in live mode. Observation deliberately records the run and
    # nothing else; dry run records nothing at all.
    if mode == MODE_LIVE and result.succeeded:
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
        "--dry-run",
        action="store_true",
        help="Touch nothing: no scan_runs row, no alerts. Local testing.",
    )
    parser.add_argument(
        "--no-alerts",
        action="store_true",
        help="Observation mode: record the scan_runs row, but persist and broadcast no alerts",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Deprecated alias for --no-alerts (the name was ambiguous: persist WHAT?)",
    )
    parser.add_argument(
        "--ignore-window",
        action="store_true",
        help="Scan at any minute, ignoring both the ET window and the tiered cadence "
             "(manual testing only)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Per-ticker rejections")
    args = parser.parse_args()
    configure_logging(args.verbose)
    sys.exit(run_cli(main(args)))
