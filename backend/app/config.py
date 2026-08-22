"""Application configuration using Pydantic settings.

Phase 0 (v2): Postgres-only. FMP and scanner threshold settings are wired here
so later phases can consume them without a config revisit; they are unused this phase.
"""

from functools import lru_cache
from typing import Annotated, List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _normalize_database_url(v: str) -> str:
    """Normalize a Postgres URL to the asyncpg driver form.

    Accepts:
      - postgres://...
      - postgresql://...
      - postgresql+asyncpg://... (already normalized)
    """
    if v.startswith("postgres://"):
        return v.replace("postgres://", "postgresql+asyncpg://", 1)
    if v.startswith("postgresql://") and "+asyncpg" not in v:
        return v.replace("postgresql://", "postgresql+asyncpg://", 1)
    return v


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignore frontend-specific VITE_* variables
    )

    # Application
    app_name: str = "Trading Alert Engine"
    app_env: str = "development"
    debug: bool = True
    log_level: str = "INFO"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Database — Postgres only. No default; must be provided.
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/trading_engine",
        description="Async Postgres DSN. SQLite is not supported.",
    )

    # Optional separate DSN for `alembic upgrade head`. When unset, migrations use
    # DATABASE_URL.
    #
    # On Supabase these should differ. The app runtime wants the TRANSACTION pooler
    # (port 6543) because it multiplexes many short-lived queries across few server
    # connections. Migrations want the SESSION pooler (port 5432), where the server
    # connection is held for the whole session: DDL, advisory locks and Alembic's
    # version-table bookkeeping all assume session continuity.
    #
    # Migrations are made pgBouncer-safe regardless (see app/core/db_connect.py), so
    # pointing this at 6543 works too — it is just not the endpoint Supabase intends
    # for DDL.
    migration_database_url: str = Field(
        default="",
        description="DSN for Alembic. Falls back to DATABASE_URL when empty.",
    )

    @field_validator("database_url", mode="after")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        v = _normalize_database_url(v)
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DATABASE_URL must be a Postgres async DSN "
                "('postgresql+asyncpg://...' or 'postgresql://...' / 'postgres://...' "
                "which are auto-normalized). SQLite is no longer supported (v2)."
            )
        return v

    @field_validator("migration_database_url", mode="after")
    @classmethod
    def validate_migration_database_url(cls, v: str) -> str:
        """Same normalization as DATABASE_URL, but empty is allowed (means 'fall back')."""
        if not v.strip():
            return ""
        v = _normalize_database_url(v)
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "MIGRATION_DATABASE_URL must be a Postgres async DSN "
                "('postgresql+asyncpg://...' or a form that auto-normalizes to it)."
            )
        return v

    @property
    def effective_migration_url(self) -> str:
        """DSN Alembic should use: MIGRATION_DATABASE_URL if set, else DATABASE_URL."""
        return self.migration_database_url or self.database_url

    # FMP — the only market-data provider. (Alpaca was removed in Phase 3.5.)
    fmp_api_key: str = ""
    fmp_base_url: str = "https://financialmodelingprep.com"

    # FMP client behaviour (Phase 1, re-tuned for Premium in Phase 4B).
    #
    # The free tier's 250 calls/day hard stop is gone: Premium has NO daily call cap
    # (750/min, 50 GB per rolling 30 days). The guard is deliberately kept anyway, but its
    # job has changed from "avoid a hard 429" to "observability and runaway protection" —
    # a bug that loops over the universe should still hit a ceiling rather than quietly
    # spend the bandwidth allowance. A full nightly cycle measures ~3,000 calls, so the
    # default leaves room without being unbounded.
    fmp_daily_budget: int = Field(
        default=20_000,
        ge=1,
        description="Daily ceiling on FMP calls. Runaway protection, not a vendor limit.",
    )
    # Bandwidth is the real Premium constraint. Tracked per UTC day by the budget guard and
    # reported by scripts/fmp_budget.py; 4A projected ~15% of the allowance at the measured
    # universe size, which is comfortable but worth seeing before it bites.
    fmp_monthly_bandwidth_gb: float = Field(
        default=50.0, gt=0, description="Vendor bandwidth allowance per rolling 30 days."
    )
    fmp_bandwidth_warn_pct: float = Field(
        default=80.0, gt=0, le=100,
        description="Warn once projected 30-day bandwidth exceeds this share of the allowance.",
    )
    fmp_timeout_seconds: float = 20.0
    # Retries apply to transient failures ONLY (5xx / network). A 429 is never retried:
    # on the free tier it means the daily cap is gone, and retrying makes it worse.
    fmp_max_retries: int = 3
    fmp_retry_backoff_seconds: float = 1.0
    # Directory holding recorded FMP responses used by tests and `--fixture` runs.
    fmp_fixtures_dir: str = "tests/fixtures/fmp"

    # RVOL implementation selector. `normalized` needs `extended=true` pre-market
    # intraday bars (FMP Premium / app V3) and raises FeatureRequiresIntraday in V1.
    rvol_mode: str = "simple"

    @field_validator("rvol_mode", mode="after")
    @classmethod
    def validate_rvol_mode(cls, v: str) -> str:
        allowed = {"simple", "normalized"}
        value = v.strip().lower()
        if value not in allowed:
            raise ValueError(f"RVOL_MODE must be one of {sorted(allowed)}, got {v!r}")
        return value

    # Scanner thresholds (tunable without redeploy). Consumed by Phase 2+.
    scanner_timezone: str = "America/New_York"
    scanner_enabled: bool = True
    scan_float_max: int = 75_000_000
    scan_avg_volume_min: int = 500_000
    scan_gap_min: float = 3.0
    scan_gap_max: float = 15.0
    scan_rvol_min: float = 10.0
    scan_upside_min: float = 5.5
    scan_price_floor: float = 2.0
    # Liquidity floor in dollars (avg 20d volume x prior close). Guards against names
    # that clear the share-count filter but are still untradeable in size.
    scan_dollar_volume_min: float = 1_000_000.0

    # Demo profile: loosens ONLY the float cap, so the free tier's mega-caps can reach
    # Stage 1 and the pipeline can be seen firing end to end on real reference data.
    # Every other threshold stays at its production value — the demo must exercise the
    # real logic, not a different one.
    scan_demo_float_max: int = 20_000_000_000
    # Default threshold profile for scans that do not name one.
    scan_profile: str = "production"

    # --- Full evaluation (Follow-up D) ---------------------------------------------
    # Compute every stage's metrics for every Stage-1 survivor, including the ones an
    # earlier stage already rejected. It CANNOT change the candidate set: the evaluation
    # passes run after every decision is made and append neither survivors nor rejections
    # (`stages._evaluate_remaining_rvol`, `stages._assign_headroom`).
    #
    # On by default because the alternative loses evidence permanently. A ticker rejected
    # on gap never has its RVOL computed, so Phase 6's threshold sweep can only report it
    # as unresolved — 94.7% of the gap-tested population, measured 13-21 August 2026 — and
    # it cannot be recovered later: pre-market bars revise upward within ~7 minutes and
    # both RVOL denominators are overwritten nightly.
    #
    # The flag exists to be a rollback, not a rollout. If a live morning ever looks wrong,
    # set it false and restart the cron rather than reverting and redeploying. Delete it
    # once a week of sessions has confirmed the candidate sets are unchanged.
    scan_full_evaluation: bool = True

    # --- Scan cadence (Follow-up A) -----------------------------------------------
    # WHEN the scanner works, as tiers: `HH:MM/interval-minutes`, comma-separated. The
    # FIRST tier's start is also when the scan window opens, so those two cannot drift.
    #
    # Measured over six live sessions (10-14, 17 August 2026; 394 completed passes) with
    # scripts/cadence_profile.py:
    #   - 04:00/04:05/04:10 produced a Stage 2 survivor in NONE of 18 session-passes. With
    #     a 7-minute settle window the 04:00 bar is not trusted until ~04:12, so they
    #     cannot, by construction. The window therefore opens at 04:15.
    #   - 04:25-06:55 is half the session's passes and a seventh of its new-and-confirmed
    #     tickers; 08:45-09:25 keeps 73% of what it surfaces. Hence 60/30/15/5.
    #
    # Safe because scans are STATELESS: the 09:25 pass recomputes every ticker from all
    # bars since 04:00 regardless of what ran before it, so no cadence can change the
    # confirmed set. It changes dashboard freshness before 09:25, and nothing else.
    #
    # In config, not literals, because the shape came from six sessions and will be
    # revisited. Validated at startup — a typo here must not silently become "no scans".
    scan_cadence_tiers: str = Field(
        default="04:15/60,07:00/30,08:00/15,08:30/5",
        description="Scan cadence as HH:MM/interval-minutes tiers. First tier opens the window.",
    )
    # How many minutes late a wake-up may be and still claim its slot. MUST stay strictly
    # below the cron's wake-up period (5 min) or one slot can be scanned twice; 0 means
    # exact-minute matching, which `at_minute` already makes tolerant of Render's 10-45 s.
    scan_cadence_grace_minutes: int = Field(default=0, ge=0, lt=5)
    #
    # NOT validated by a field validator here, deliberately. The spec's meaning is defined
    # by `scanner.cadence.parse_cadence`, and importing it from a validator initialises the
    # scanner package -> models -> `core.database`, which reads settings at import time:
    # a genuine circular import, caught by the test suite refusing to collect. Duplicating
    # a syntax check here instead would be a second definition of "valid", free to drift
    # from the one that decides when scans run.
    #
    # `load_cadence()` parses and raises instead, and every scanning entry point calls it
    # before touching FMP or the database — `scripts/run_scan.py` at the top of `main()`,
    # and `Scanner.__init__`. A typo in SCAN_CADENCE_TIERS therefore fails the cron run
    # immediately and visibly, which is what startup validation was for.
    # Snapshot scenario feeding Stage 2 in V1 (no live pre-market data on the free tier).
    scan_snapshot_fixture: str = "tests/fixtures/snapshots/demo_session.json"

    # --- Bar settling (Phase 4B) --------------------------------------------------
    # Phase 4A measured that 49.4% of pre-market bars are revised UPWARD after first
    # publication (median +24.2%, worst +7,156%), and that every observed revision settled
    # within 7 minutes of the bar closing. A bar younger than this window is provisional.
    #
    # NOT hardcoded, deliberately: 7 minutes comes from one ordinary session. A volatile or
    # holiday-shortened morning could report later, and a hardcoded slice would silently
    # become wrong on exactly the days that matter most.
    bar_settle_minutes: int = Field(
        default=7, ge=0,
        description="A bar is provisional until this many minutes after it closes.",
    )

    # --- Universe build (Phase 4B) ------------------------------------------------
    # The Stage-1 universe size is DISCOVERED nightly, never configured. 4A measured 554,
    # but that is one day's output of a filter that moves with price, volume, float,
    # listings — and immediately with any threshold edit. These two settings only bound
    # what counts as a surprise.
    universe_size_ceiling: int = Field(
        default=3_500, ge=1,
        description="Warn above this many tickers: 4A projects bandwidth pressure past it.",
    )
    universe_size_move_pct: float = Field(
        default=50.0, gt=0,
        description="Warn when the universe moves this % from its trailing median.",
    )
    # The screener reports a LIVE price; the scanner compares against the prior close. A
    # name just under the floor tonight can gap through it tomorrow morning, and anything
    # the pre-filter drops is never seen again by any later stage. So the universe admits
    # names somewhat below the floor and lets the risk filter reject them at scan time,
    # where the rejection is visible and reversible.
    universe_price_margin_pct: float = Field(
        default=20.0, ge=0, lt=100,
        description="Admit names this % below the price floor, to avoid permanent exclusion.",
    )

    # --- Nightly reference refresh (Phase 4B) -------------------------------------
    # `historical-price-eod/full` returns EVERYTHING — 1,254 daily bars for AAPL, 231 KB.
    # The deepest metric computed from it is SMA-200, which needs 200 trading days, so the
    # other ~1,000 bars are pure bandwidth. Measured: bounding the request to 400 calendar
    # days returns 276 bars for 51 KB, a 78% reduction, which across a 3,948-ticker nightly
    # refresh is 19.2 GB/month -> 4.2 GB/month against a 50 GB allowance.
    #
    # 400 days rather than 300: holidays and halts mean calendar days overstate trading
    # days, and a ticker that silently returns 199 bars would produce a null SMA-200 and
    # drop out of Stage 3 with no obvious cause.
    reference_history_days: int = Field(
        default=400, ge=250,
        description="Calendar days of EOD history to request per ticker.",
    )

    # --- Live snapshot fan-out (Phase 4C) -----------------------------------------
    # `batch-quote` returns the PREVIOUS session's close during pre-market (measured, 4A),
    # so the live snapshot is one `historical-chart/5min?extended=true` call per Stage-1
    # candidate. At ~694 candidates that is ~0.7 min per pass against FMP's 750/min.
    #
    # The per-minute cap is set below the vendor's so a burst cannot trip it; concurrency
    # bounds how many are in flight at once. Both are config because the Stage-1 count is
    # discovered nightly and can move a long way after a threshold edit.
    live_snapshot_concurrency: int = Field(default=8, ge=1, le=64)
    live_snapshot_max_per_minute: int = Field(default=700, ge=1)

    # --- Data-quality suppression (post-4C hotfix) --------------------------------
    # A candidate whose computed upside exceeds this is REJECTED as a data-quality risk
    # filter, not surfaced. It does not change Stage 1/2/3 arithmetic — docs/CLAUDE.md §4.3
    # provides for exactly this kind of veto.
    #
    # Measured basis: the scanner is a feasibility screen for a ~5% intraday move, and
    # `scan_upside_min` is 5.5%. An upside of 540% (FFAI, 7 Aug 2026) does not mean a
    # better opportunity — it means the nearest resistance sits in a price regime the stock
    # has left. FFAI fell 32.06 -> 4.38 in twenty sessions; its 50-day average is 7x the
    # price because that is where it used to trade, not because anything attracts it there.
    #
    # 100% is deliberately generous: a genuine post-crash retrace toward a 20-day high can
    # legitimately offer 50-80%, and the point is to remove the meaningless tail, not to
    # second-guess the strategy. These candidates sort to the TOP of a list ranked by
    # upside, so the tail is what the end user sees first.
    scan_upside_max: float = Field(
        default=100.0, gt=0,
        description="Reject candidates whose upside% exceeds this — implausible reference.",
    )
    # Ratio of 20-day high to prior close above which a ticker's resistance levels are
    # treated as belonging to an abandoned price regime.
    scan_price_regime_break_ratio: float = Field(
        default=3.0, gt=1,
        description="Reject when high_20d / price_close_yesterday exceeds this.",
    )

    # --- Data-integrity guards (Phase 4C) -----------------------------------------
    # Accumulated pre-market volume above this multiple of volume_avg_20d is more likely a
    # data fault than a real event. Flagged, not silently dropped — a genuine 30x morning
    # is exactly what the scanner exists to find, so the operator decides.
    scan_volume_sanity_multiple: float = Field(default=50.0, gt=0)

    # --- Pre-market volume profiles (Phase 4B) ------------------------------------
    # Target sessions per profile. Below `profile_sessions_min` a profile is FLAGGED as
    # thin rather than silently averaged — a 3-session profile must never be mistaken for
    # a 20-session one by the RVOL that divides by it.
    profile_sessions_target: int = Field(default=20, ge=1)
    profile_sessions_min: int = Field(default=10, ge=1)
    # The per-request row cap truncates long ranges (4A measured truncation between 950 and
    # 1,936 bars), so history is fetched a week at a time.
    profile_fetch_days_per_request: int = Field(default=7, ge=1, le=31)

    # --- Confidence score weights (must sum to 1.0; validated at startup) ---------
    # PROVISIONAL. These are reasoned assumptions, not fitted parameters — nothing has
    # been backtested yet (app V3, Phase 6). The API and UI label every score as such.
    score_weight_gap: float = 0.20
    score_weight_rvol: float = 0.30
    score_weight_upside: float = 0.25
    score_weight_liquidity: float = 0.15
    score_weight_data_quality: float = 0.10

    # Where in the gap band the setup is considered strongest, as a fraction of the band.
    # 0.25 of a 3-15% band = ~6%: past the noise floor, with most of the move still ahead.
    score_gap_peak_position: float = 0.25
    # RVOL saturates at this multiple of the threshold (10 x 10% = 100% of average).
    score_rvol_saturation_multiple: float = 10.0
    # Upside saturates at this multiple of the threshold (3 x 5.5% = 16.5%).
    score_upside_saturation_multiple: float = 3.0
    # Liquidity saturates at this multiple of the dollar-volume floor.
    score_liquidity_saturation_multiple: float = 100.0

    # Score assigned to the headroom factor when upside_pct is NULL. Neutral by design:
    # a ticker with no overhead resistance has UNMEASURED headroom, which is neither the
    # worst case (0.0) nor a proven good one (1.0). See docs/CLAUDE.md 4.3 "Breakout
    # convention" — that rejection is a deferred strategy decision, and this fallback is
    # what lets it be reversed without touching the scoring signature.
    score_null_upside_fallback: float = 0.5

    # Data-quality penalties, subtracted from a 1.0 baseline and clamped at 0.
    score_penalty_demo_profile: float = 0.5
    score_penalty_approximate_rvol: float = 0.25
    score_penalty_fixture_snapshot: float = 0.25
    score_penalty_stale_reference: float = 0.25
    score_penalty_null_upside: float = 0.15
    # Reference data older than this many days is considered stale.
    score_reference_max_age_days: int = 4

    # CORS — Vercel frontend origin(s) go here in production, comma-separated or JSON array.
    # NoDecode disables pydantic-settings' JSON pre-parse so a plain comma list works.
    cors_origins: Annotated[List[str], NoDecode] = [
        "http://localhost:5173",
        "http://localhost:3000",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        """Accept either a JSON array or a comma-separated string in env."""
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("["):
                import json

                return json.loads(s)
            return [origin.strip() for origin in s.split(",") if origin.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
