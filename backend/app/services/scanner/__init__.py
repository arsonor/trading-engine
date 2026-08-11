"""Pre-market scanner services (v2).

The three-stage filtration pipeline from `docs/CLAUDE.md` section 4. Stage 1 and Stage 3
run on real EOD reference data in V1; Stage 2 is complete but fed by fixture snapshots
until FMP Starter provides live pre-market data (app V2).
"""

from app.services.scanner.candidate import (
    STAGE_1,
    STAGE_2,
    STAGE_3,
    STAGE_RISK,
    Candidate,
    Rejection,
    StageOutcome,
)
from app.services.scanner.clock import (
    ET,
    FINAL_PASS_TIME,
    SCAN_WINDOW_END,
    SCAN_WINDOW_START,
    Clock,
    FixedClock,
    SystemClock,
    at_minute,
    describe,
    is_final_pass,
    is_within_scan_window,
    parse_scan_time,
    to_et,
    to_utc,
)
from app.services.scanner.errors import (
    FeatureRequiresIntraday,
    InsufficientRvolData,
    ScannerError,
)
from app.services.scanner.pipeline import Scanner, ScanResult, StageCounts
from app.services.scanner.profiles import (
    DEMO,
    PRODUCTION,
    ThresholdProfile,
    available_profiles,
    demo_profile,
    get_profile,
    production_profile,
)
from app.services.scanner.risk import (
    MarketTape,
    MarketTapeProvider,
    NeutralMarketTape,
    apply_risk_filters,
)
from app.services.scanner.rvol import (
    MODE_NORMALIZED,
    MODE_SIMPLE,
    NormalizedRvol,
    RvolCalculator,
    RvolContext,
    RvolResult,
    SimpleRvol,
    get_rvol_calculator,
)
from app.services.scanner.snapshot import (
    FixtureSnapshotProvider,
    FmpLiveSnapshotProvider,
    MarketSnapshot,
    SnapshotProvider,
    SnapshotUnavailable,
)
from app.services.scanner.stages import (
    stage_1_liquidity,
    stage_2_momentum,
    stage_3_room_to_run,
)

__all__ = [
    "DEMO",
    "ET",
    "FINAL_PASS_TIME",
    "MODE_NORMALIZED",
    "MODE_SIMPLE",
    "PRODUCTION",
    "SCAN_WINDOW_END",
    "SCAN_WINDOW_START",
    "STAGE_1",
    "STAGE_2",
    "STAGE_3",
    "STAGE_RISK",
    "Candidate",
    "Clock",
    "FeatureRequiresIntraday",
    "FixedClock",
    "FixtureSnapshotProvider",
    "FmpLiveSnapshotProvider",
    "InsufficientRvolData",
    "MarketSnapshot",
    "MarketTape",
    "MarketTapeProvider",
    "NeutralMarketTape",
    "NormalizedRvol",
    "Rejection",
    "RvolCalculator",
    "RvolContext",
    "RvolResult",
    "ScanResult",
    "Scanner",
    "ScannerError",
    "SimpleRvol",
    "SnapshotProvider",
    "SnapshotUnavailable",
    "StageCounts",
    "StageOutcome",
    "SystemClock",
    "ThresholdProfile",
    "apply_risk_filters",
    "at_minute",
    "available_profiles",
    "demo_profile",
    "describe",
    "get_profile",
    "get_rvol_calculator",
    "is_final_pass",
    "is_within_scan_window",
    "parse_scan_time",
    "production_profile",
    "stage_1_liquidity",
    "stage_2_momentum",
    "stage_3_room_to_run",
    "to_et",
    "to_utc",
]
