"""Live market state for Stage 2, behind a provider interface.

Stage 2 needs two numbers per ticker that V1 cannot get: the current pre-market price and
the volume accumulated since 04:00 ET. FMP's free tier has no real-time quote and no
intraday bars at all, so in V1 those numbers come from recorded fixtures while the *logic*
consuming them is complete and final.

Two providers:

  * `FixtureSnapshotProvider` — V1. Reads a JSON scenario file.
  * `FmpLiveSnapshotProvider` — V2. Documented and stubbed here so the shape of the
    seam is fixed now; it raises rather than pretending.

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

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from app.services.scanner.candidate import Candidate
from app.services.scanner.errors import ScannerError

logger = logging.getLogger(__name__)

SOURCE_FIXTURE = "fixture"
SOURCE_FMP_LIVE = "fmp-live"


class SnapshotUnavailable(ScannerError):
    """No snapshot could be produced for a ticker — it is skipped, not zero-valued."""


@dataclass(frozen=True)
class MarketSnapshot:
    """Point-in-time pre-market state for one ticker."""

    ticker: str
    price: float
    volume_premarket_accumulated: float
    as_of: datetime
    source: str

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
    """Live pre-market snapshots from FMP — implemented in Phase 4 (app V2).

    The contract a V2 implementation must satisfy:

      * `price` comes from FMP's pre/after-market quote endpoint, available from the
        Starter tier.
      * `volume_premarket_accumulated` is the hard part. FMP support confirmed Starter's
        intraday bars are regular-hours only (`extended=true` is Premium), so V2 must
        use whatever pre-market volume the quote endpoints expose and flag the resulting
        RVOL as approximate on every alert — see `SimpleRvol`.
      * Every call goes through `DailyBudgetGuard`, like every other FMP path.
      * Tickers the plan cannot serve are omitted from the result, never zero-filled.
    """

    source = SOURCE_FMP_LIVE

    async def get_snapshots(
        self, candidates: list[Candidate], as_of: datetime
    ) -> dict[str, MarketSnapshot]:
        raise ScannerError(
            "Live pre-market snapshots require FMP Starter (app V2) — the free tier has "
            "no real-time quote and no intraday bars. Run with --fixture until then; the "
            "V2 implementation drops in behind this same SnapshotProvider interface."
        )
