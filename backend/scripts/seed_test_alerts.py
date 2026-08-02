"""Seed sample scanner alerts so the dashboard has something to render.

    uv run python scripts/seed_test_alerts.py
    uv run python scripts/seed_test_alerts.py --clear
    uv run python scripts/seed_test_alerts.py --session 2026-07-28

The rows follow the v2 alert contract (`docs/CLAUDE.md` section 4.4) and are stamped with
the `demo` profile, so the dashboard badges them as illustrative — exactly like a real
demo scan. They are deliberately NOT random: a smoke test that produces different numbers
each run cannot be compared against anything.

For an end-to-end check of the actual pipeline, prefer:

    uv run python scripts/run_scan.py --fixture --profile demo

This script exists for the case where you want alerts on screen without reference data
loaded.
"""

import argparse
from datetime import date, datetime

# Import first: puts the backend directory on sys.path for the `app.*` imports below.
from _bootstrap import configure_logging, run_cli
from sqlalchemy import delete, select

from app.core.database import async_session_maker
from app.models.alert import Alert
from app.models.scan_run import ScanRun, ScanRunStatus

DEMO_PROFILE = "demo"

# (ticker, gap%, rvol%, entry price, nearest resistance, source, upside%, confidence)
# The last entry has no resistance above price — the breakout case, where upside is
# unmeasured rather than zero. Keeping it here means the dashboard's null-upside state
# gets exercised every time someone seeds.
SAMPLE_ALERTS = [
    ("ADBE", 7.00, 25.00, 240.87, 278.81, "sma_200", 15.75, 0.62),
    ("BA", 5.00, 40.00, 220.00, 237.48, "high_20d", 7.95, 0.48),
    ("C", 3.50, 18.00, 136.82, 145.10, "high_20d", 6.05, 0.32),
    ("BRKO", 5.00, 35.00, 349.67, None, None, None, 0.41),
]


async def seed(session_date: date, clear: bool) -> int:
    async with async_session_maker() as db:
        if clear:
            removed = await db.execute(
                delete(Alert).where(Alert.session_date == session_date)
            )
            await db.commit()
            print(f"[OK] Cleared {removed.rowcount or 0} existing alert(s) for {session_date}")

        # A scan_run to hang the alerts off, so the scan-status panel has something
        # coherent to show rather than "never run" beside a list of candidates.
        run = ScanRun(
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
            status=ScanRunStatus.COMPLETED,
            profile=DEMO_PROFILE,
            api_calls_used=0,
            stage_counts_json={
                "as_of_et": f"{session_date}T09:25:00-04:00",
                "is_final_pass": True,
                "profile": {"name": DEMO_PROFILE, "is_demo": True},
                "counts": {
                    "universe": 10,
                    "stage_1_liquidity": 10,
                    "stage_2_momentum": 6,
                    "stage_3_room_to_run": len(SAMPLE_ALERTS),
                    "risk_filters": len(SAMPLE_ALERTS),
                },
                "candidates": [row[0] for row in SAMPLE_ALERTS],
                "rejections": [],
                "snapshot_source": "seed-script",
                "rvol_mode": "simple",
            },
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)

        created = 0
        for ticker, gap, rvol, entry, resistance, source, upside, score in SAMPLE_ALERTS:
            existing = await db.scalar(
                select(Alert).where(
                    Alert.ticker == ticker, Alert.session_date == session_date
                )
            )
            if existing is not None:
                print(f"  {ticker}: already present for {session_date}, skipped")
                continue

            db.add(
                Alert(
                    ticker=ticker,
                    session_date=session_date,
                    timestamp=datetime.utcnow(),
                    scan_timestamp=datetime.utcnow(),
                    scan_run_id=run.id,
                    profile=DEMO_PROFILE,
                    gap_pct=gap,
                    rvol_pct=rvol,
                    rvol_mode="simple",
                    rvol_is_approximate=True,
                    entry_reference_price=entry,
                    nearest_resistance=resistance,
                    resistance_source=source,
                    upside_pct=upside,
                    suggested_entry_window="09:30-10:00 ET (first 30 minutes)",
                    confidence_score=score,
                    is_final_pass=True,
                    is_read=False,
                    score_breakdown_json={
                        "score": score,
                        "is_provisional": True,
                        "profile": DEMO_PROFILE,
                        "uses_fallback": upside is None,
                        "factors": [],
                        "notes": [
                            "Seeded by scripts/seed_test_alerts.py — not produced by a "
                            "real scan.",
                        ],
                    },
                )
            )
            created += 1

        await db.commit()

    print(f"[OK] Seeded {created} alert(s) for session {session_date} (profile={DEMO_PROFILE})")
    print(f"  scan_runs.id : {run.id}")
    print("  These are DEMO-profile rows and the dashboard badges them as illustrative.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed sample scanner alerts.")
    parser.add_argument(
        "--session", help="Session date (YYYY-MM-DD). Defaults to today.", default=None
    )
    parser.add_argument(
        "--clear", action="store_true", help="Delete existing alerts for that session first"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)

    session_date = date.fromisoformat(args.session) if args.session else date.today()
    raise SystemExit(run_cli(seed(session_date, args.clear)))
