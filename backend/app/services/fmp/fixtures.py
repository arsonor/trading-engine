"""Fixture recording and replay for FMP.

The scanner cannot be tested against a live market-hours API: responses change, the free
tier has 250 calls a day, and CI would burn the quota. So real responses are captured
once and replayed forever.

Both clients subclass `FmpClient` and override only `_raw_get`. Everything above that
seam — status classification, error taxonomy, pydantic validation — is the same code in
tests as in production.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services.fmp.budget import DailyBudgetGuard, NullBudgetGuard
from app.services.fmp.client import EP_EOD_FULL, FmpClient
from app.services.fmp.errors import FmpError
from app.services.fmp.parsing import RawResponse

logger = logging.getLogger(__name__)

# Recorded EOD history is trimmed to this many bars: enough for SMA-200 with headroom,
# small enough that fixtures stay reviewable in a diff.
EOD_FIXTURE_BARS = 260


class FixtureNotFound(FmpError):
    """No recording exists for this request — record it before replaying it."""

    def __init__(self, key: str, root: Path) -> None:
        self.key = key
        super().__init__(
            f"No FMP fixture {key!r} under {root}. "
            f"Record it with `uv run python scripts/record_fmp_fixtures.py`."
        )


def fixture_key(endpoint: str, params: dict[str, Any]) -> str:
    """Stable filename-safe key for an (endpoint, params) pair."""
    parts = [f"{k}={params[k]}" for k in sorted(params) if k != "apikey"]
    stem = endpoint.replace("/", "_")
    if parts:
        stem = f"{stem}__{'__'.join(parts)}"
    safe = "".join(c if c.isalnum() or c in "-_=." else "-" for c in stem)
    if len(safe) > 100:
        digest = hashlib.sha1(safe.encode()).hexdigest()[:10]
        safe = f"{safe[:80]}-{digest}"
    return safe


class FixtureStore:
    """Reads and writes recorded FMP responses as JSON files."""

    def __init__(self, root: str | Path | None = None) -> None:
        if root is None:
            root = get_settings().fmp_fixtures_dir
        self.root = Path(root)

    def path_for(self, endpoint: str, params: dict[str, Any]) -> Path:
        return self.root / f"{fixture_key(endpoint, params)}.json"

    def has(self, endpoint: str, params: dict[str, Any]) -> bool:
        return self.path_for(endpoint, params).exists()

    def save(
        self, endpoint: str, params: dict[str, Any], status: int, payload: Any, note: str = ""
    ) -> Path:
        path = self.path_for(endpoint, params)
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "endpoint": endpoint,
            "params": {k: v for k, v in params.items() if k != "apikey"},
            "status": status,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "note": note,
            "payload": payload,
        }
        path.write_text(json.dumps(document, indent=2, default=str), encoding="utf-8")
        return path

    def load(self, endpoint: str, params: dict[str, Any]) -> RawResponse:
        path = self.path_for(endpoint, params)
        if not path.exists():
            raise FixtureNotFound(fixture_key(endpoint, params), self.root)
        document = json.loads(path.read_text(encoding="utf-8"))
        return RawResponse(status=int(document.get("status", 200)), payload=document.get("payload"))

    def keys(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.stem for p in self.root.glob("*.json"))


class FixtureFmpClient(FmpClient):
    """Serves recorded responses. Makes no network calls.

    A budget guard can still be injected: replay costs no real quota, but reserving
    against a test guard is what lets budget-exhaustion behaviour be tested without
    spending 250 real calls to get there.
    """

    def __init__(
        self, store: FixtureStore | None = None, budget: DailyBudgetGuard | None = None
    ) -> None:
        super().__init__(api_key="fixture", budget=budget or NullBudgetGuard())
        self.store = store or FixtureStore()

    async def _raw_get(self, endpoint: str, params: dict[str, Any]) -> RawResponse:
        await self._budget.reserve(endpoint)
        return self.store.load(endpoint, params)

    async def aclose(self) -> None:
        return None


class RecordingFmpClient(FmpClient):
    """A live client that writes every response to the fixture store as it goes.

    This is the ONLY code path that touches live FMP outside manual runs, and it is still
    budget-guarded — recording a fixture spends real quota.
    """

    def __init__(self, store: FixtureStore | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.store = store or FixtureStore()
        self.recorded: list[Path] = []

    async def _raw_get(self, endpoint: str, params: dict[str, Any]) -> RawResponse:
        raw = await super()._raw_get(endpoint, params)
        payload = raw.payload
        if endpoint == EP_EOD_FULL and isinstance(payload, list):
            # Trim to a reviewable window; sort newest-first so the trim keeps recent bars.
            payload = sorted(payload, key=lambda r: str(r.get("date", "")), reverse=True)[
                :EOD_FIXTURE_BARS
            ]
        path = self.store.save(endpoint, params, raw.status, payload)
        self.recorded.append(path)
        logger.info("Recorded fixture %s (HTTP %s)", path.name, raw.status)
        return RawResponse(raw.status, payload)
