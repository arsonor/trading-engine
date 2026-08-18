"""Live market state for Stage 2, behind a provider interface.

Stage 2 needs two numbers per ticker: the current pre-market price and the volume
accumulated since 04:00 ET. Which provider supplies them is a config choice, and both are
first-class — the fixture path is how the pipeline is tested offline and how the demo
profile is demonstrated, so it does not go away now that live data exists.

Two providers:

  * `FixtureSnapshotProvider` — reads a JSON scenario file. No API calls.
  * `FmpLiveSnapshotProvider` — Phase 4C. One `historical-chart/5min?extended=true` call
    per Stage-1 candidate, summed over settled bars.

Fixture scenarios accept absolute or relative values per ticker:

```json
{
  "as_of": "2026-07-28T08:45:00-04:00",
  "snapshots": {
    "ADBE": {"gap_pct": 7.0, "premarket_volume_ratio": 0.25},
    "AAPL": {"price": 349.67, "premarket_volume": 15000000}
  }
}
```

Relative keys are resolved against the ticker's own reference data, which is what makes a
scenario survive a nightly reference refresh: "gap up 7%" stays a 7% gap tomorrow, while a
hardcoded price silently becomes a 2% gap. Absolute keys stay available for golden tests
that need to pin an exact number.

`premarket_volume_ratio` is the inverse of `SimpleRvol` (volume / volume_avg_20d), so a
ratio of 0.25 produces an RVOL of 25% when the scanner recomputes it. The scenario does
not set RVOL directly — the real calculator still does the work.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.services.bars import Bar, premarket_bars, settled_bars
from app.services.scanner.candidate import Candidate
from app.services.scanner.errors import ScannerError

logger = logging.getLogger(__name__)

SOURCE_FIXTURE = "fixture"
SOURCE_FMP_LIVE = "fmp-live"


class SnapshotUnavailable(ScannerError):
    """No snapshot could be produced for a ticker — it is skipped, not zero-valued."""


@dataclass(frozen=True)
class MarketSnapshot:
    """Point-in-time pre-market state for one ticker.

    `settled_through` is the load-bearing field, not `as_of`. Phase 4A measured that 49.4%
    of pre-market bars are revised upward after publication, all settling within ~7 minutes
    of the bar closing, so a snapshot taken at 09:25 can only *honestly* account for volume
    up to roughly 09:13. That earlier instant is what RVOL must divide by the profile at —
    dividing volume-through-09:13 by expected-at-09:25 understates RVOL by construction.

    Providers that have no notion of settling (the fixture) leave it None, and RVOL falls
    back to `as_of`, which is the correct reading for authored scenarios: their volumes are
    whatever the author declared, complete as of the declared instant.
    """

    ticker: str
    price: float
    volume_premarket_accumulated: float
    as_of: datetime
    source: str
    # The effective cut-off: end of the newest bar old enough to be trusted.
    settled_through: datetime | None = None
    # How many bars were dropped for being too fresh. Recorded on the alert so V3 can tell
    # "the scanner was wrong" from "the data was revised after the scanner saw it".
    provisional_bars_excluded: int = 0
    bars_used: int = 0

    def __post_init__(self) -> None:
        if self.price <= 0:
            raise ValueError(f"{self.ticker}: snapshot price must be positive, got {self.price}")
        if self.volume_premarket_accumulated < 0:
            raise ValueError(
                f"{self.ticker}: accumulated volume cannot be negative, "
                f"got {self.volume_premarket_accumulated}"
            )


@runtime_checkable
class SnapshotProvider(Protocol):
    """Supplies pre-market snapshots for a set of Stage-1 survivors.

    Takes `Candidate` objects rather than bare tickers so a provider may resolve values
    relative to reference data. The live provider ignores everything but `.ticker`.
    """

    source: str

    async def get_snapshots(
        self, candidates: list[Candidate], as_of: datetime
    ) -> dict[str, MarketSnapshot]:
        """Return a snapshot per ticker. Tickers with no data are simply absent."""
        ...


class FixtureSnapshotProvider:
    """Serves snapshots from a recorded/authored JSON scenario. Makes no API calls."""

    source = SOURCE_FIXTURE

    def __init__(
        self, scenario_path: str | Path | None = None, scenario: dict[str, Any] | None = None
    ) -> None:
        if scenario is None:
            if scenario_path is None:
                raise ValueError("FixtureSnapshotProvider needs a scenario path or dict")
            path = Path(scenario_path)
            if not path.exists():
                raise FileNotFoundError(
                    f"Snapshot scenario {path} not found. Author one, or pass --snapshot-file."
                )
            scenario = json.loads(path.read_text(encoding="utf-8"))
            self.path = path
        else:
            self.path = None

        self.scenario = scenario
        self.name = scenario.get("name", self.path.stem if self.path else "inline")
        self._specs: dict[str, dict] = {
            ticker.upper(): spec for ticker, spec in scenario.get("snapshots", {}).items()
        }

    @property
    def declared_as_of(self) -> datetime | None:
        """The scenario's own timestamp, if it declares one."""
        raw = self.scenario.get("as_of")
        return datetime.fromisoformat(raw) if raw else None

    def tickers(self) -> list[str]:
        return sorted(self._specs)

    async def get_snapshots(
        self, candidates: list[Candidate], as_of: datetime
    ) -> dict[str, MarketSnapshot]:
        snapshots: dict[str, MarketSnapshot] = {}
        for candidate in candidates:
            spec = self._specs.get(candidate.ticker.upper())
            if spec is None:
                continue
            try:
                snapshots[candidate.ticker] = self._build(candidate, spec, as_of)
            except SnapshotUnavailable as exc:
                logger.warning("Snapshot skipped: %s", exc)
        return snapshots

    def _build(self, candidate: Candidate, spec: dict, as_of: datetime) -> MarketSnapshot:
        price = self._resolve_price(candidate, spec)
        volume = self._resolve_volume(candidate, spec)
        return MarketSnapshot(
            ticker=candidate.ticker,
            price=price,
            volume_premarket_accumulated=volume,
            as_of=as_of,
            source=self.source,
        )

    @staticmethod
    def _resolve_price(candidate: Candidate, spec: dict) -> float:
        if "price" in spec:
            return float(spec["price"])
        if "gap_pct" in spec:
            if candidate.price_close_yesterday is None:
                raise SnapshotUnavailable(
                    f"{candidate.ticker}: scenario uses gap_pct but the ticker has no "
                    f"price_close_yesterday in reference_data"
                )
            return candidate.price_close_yesterday * (1 + float(spec["gap_pct"]) / 100)
        raise SnapshotUnavailable(
            f"{candidate.ticker}: scenario entry needs either 'price' or 'gap_pct'"
        )

    @staticmethod
    def _resolve_volume(candidate: Candidate, spec: dict) -> float:
        if "premarket_volume" in spec:
            return float(spec["premarket_volume"])
        if "premarket_volume_ratio" in spec:
            if not candidate.volume_avg_20d:
                raise SnapshotUnavailable(
                    f"{candidate.ticker}: scenario uses premarket_volume_ratio but the "
                    f"ticker has no volume_avg_20d in reference_data"
                )
            return candidate.volume_avg_20d * float(spec["premarket_volume_ratio"])
        raise SnapshotUnavailable(
            f"{candidate.ticker}: scenario entry needs either 'premarket_volume' or "
            f"'premarket_volume_ratio'"
        )


class FmpLiveSnapshotProvider:
    """Live pre-market snapshots from FMP Premium `extended=true` intraday bars.

    ## Why one call per ticker rather than a batch

    Phase 4A measured that `batch-quote` — the obvious cheap path, and what earlier
    planning assumed — returns the **previous regular session's close** during pre-market.
    At 04:22 ET it reported AAPL at 311 with 44.3M volume stamped the prior day, while the
    extended bars showed 313.96 with 43,030 pre-market shares. So there is no batch route
    to live pre-market state; it is `historical-chart/5min?extended=true` per candidate.

    That is affordable only because the Stage-1 set is small: ~736 tickers (measured
    18 August 2026 at 737 calls a pass; ~694 when this was written) against the 700
    calls/minute pacer is just over a minute per pass, inside the 5-minute cadence.

    ## Three behaviours that are easy to get wrong

    * **Volume is per-bar, not cumulative** (measured: AAPL 30,243 -> 9,965 -> 2,822 across
      consecutive bars). Accumulated pre-market volume is a SUM. Reading the newest bar's
      `volume` would yield the last five minutes and call it the session.
    * **An empty array means the ticker has not traded yet** — a normal, expected state,
      watched live in 4A as EROC returned `[]` three times and then converted to real bars.
      It is not an error and must not become a zero, which would read as measured
      stillness and hand RVOL a real-looking 0%.
    * **Fresh bars are provisional.** 49.4% of bars are revised upward, settling within
      ~7 minutes. The sum therefore runs over `settled_bars()` only, and the snapshot
      carries the cut-off so RVOL divides by the profile at the same instant.

    Individual failures are recorded and skipped. One unreachable ticker must not cost the
    morning's scan.
    """

    source = SOURCE_FMP_LIVE

    def __init__(
        self,
        client: Any | None = None,
        *,
        concurrency: int | None = None,
        max_per_minute: int | None = None,
        settle_minutes: int | None = None,
    ) -> None:
        settings = get_settings()
        self._client = client
        self._owns_client = client is None
        self._concurrency = concurrency or settings.live_snapshot_concurrency
        self._max_per_minute = max_per_minute or settings.live_snapshot_max_per_minute
        self._settle_minutes = settle_minutes
        self._tz = ZoneInfo(settings.scanner_timezone)
        # Populated per run; the pipeline reads these for `scan_runs`.
        self.failures: dict[str, str] = {}
        self.not_trading: list[str] = []

    async def get_snapshots(
        self, candidates: list[Candidate], as_of: datetime
    ) -> dict[str, MarketSnapshot]:
        from app.services.fmp.client import FmpClient

        self.failures = {}
        self.not_trading = []
        if not candidates:
            return {}

        client = self._client or FmpClient()
        semaphore = asyncio.Semaphore(self._concurrency)
        pacer = _RatePacer(self._max_per_minute)
        session_date = as_of.astimezone(self._tz).date()

        async def one(candidate: Candidate) -> tuple[str, MarketSnapshot | None]:
            async with semaphore:
                await pacer.wait()
                try:
                    bars = await client.get_intraday_bars(
                        candidate.ticker, interval="5min",
                        start=session_date, end=session_date, extended=True,
                    )
                except Exception as exc:  # noqa: BLE001 - one ticker must not fail the scan
                    self.failures[candidate.ticker] = f"{type(exc).__name__}: {exc}"[:300]
                    return candidate.ticker, None
            return candidate.ticker, self._build(candidate, bars, as_of)

        try:
            results = await asyncio.gather(*(one(c) for c in candidates))
        finally:
            if self._owns_client:
                await client.aclose()

        snapshots = {t: s for t, s in results if s is not None}
        if self.failures:
            logger.warning(
                "Live snapshots: %s of %s ticker(s) failed and were skipped: %s",
                len(self.failures), len(candidates),
                ", ".join(sorted(self.failures)[:10]),
            )
        return snapshots

    def _build(
        self, candidate: Candidate, rows: list[Any], as_of: datetime
    ) -> MarketSnapshot | None:
        """Turn today's bars into a snapshot, or None when the ticker has not traded."""
        if not rows:
            self.not_trading.append(candidate.ticker)
            return None

        bars = [
            Bar(start=r.date.replace(tzinfo=self._tz), volume=r.volume, close=r.close)
            for r in rows
        ]
        # Only the pre-market window, and never beyond the scan moment: a pass simulated at
        # 06:00 must not see 09:00 bars just because the request returned the whole day.
        window = [b for b in premarket_bars(bars) if b.start <= as_of]
        settled = settled_bars(window, now=as_of, exclusion_minutes=self._settle_minutes)

        if not settled:
            # Traded, but only within the settling window — nothing trustworthy yet.
            self.not_trading.append(candidate.ticker)
            return None

        total = sum(b.volume or 0.0 for b in settled)
        last = settled[-1]
        price = last.close
        if not price or price <= 0:
            self.failures[candidate.ticker] = "last settled bar has no usable close price"
            return None

        return MarketSnapshot(
            ticker=candidate.ticker,
            price=float(price),
            volume_premarket_accumulated=float(total),
            as_of=as_of,
            source=self.source,
            settled_through=last.end,
            provisional_bars_excluded=len(window) - len(settled),
            bars_used=len(settled),
        )


class _RatePacer:
    """Spaces request starts so a burst cannot trip the vendor's per-minute limit.

    A semaphore bounds how many calls are *in flight*; it does not bound how many *start*
    per minute. With 8 in flight at ~0.3s each, 694 tickers would issue ~1,600 requests a
    minute against a 750 ceiling. This adds the missing constraint.
    """

    def __init__(self, max_per_minute: int) -> None:
        self._interval = 60.0 / max(1, max_per_minute)
        self._next_at = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_at - now)
            self._next_at = max(now, self._next_at) + self._interval
        if delay:
            await asyncio.sleep(delay)
