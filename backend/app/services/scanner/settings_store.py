"""Runtime threshold overrides.

`docs/CLAUDE.md` calls for thresholds tunable *without a redeploy*, because the end
user's strategy will evolve and a deploy cycle is not an acceptable price for changing a
number. Environment variables alone cannot do that: changing one restarts the service.

Three layers, most specific wins:

    env defaults (SCAN_*)  ->  scanner_settings row  ->  explicit per-run argument

An absent row means "use the environment", so a fresh deploy needs no seed data. Only
keys the user actually changed are stored, so a later change to an env default still
reaches anything the user has not pinned.

## Overrides are scoped PER PROFILE

`overrides_json` is keyed by profile name::

    {"production": {"gap_min": 2.5}, "demo": {"upside_min": 14.0}}

They used to be one flat set applied on top of whichever profile was active, which had a
specific and nasty failure: the demo profile exists for exactly one reason — loosen the
float cap so free-tier mega-caps reach Stage 1 — and a user saving thresholds while
thinking in production terms silently reverted that cap. The result presented as
"0 candidates, successful scan, quiet market", which is precisely the confusion the whole
scan-status design exists to prevent.

Demo and production are different regimes with different intended values, so they do not
share an override set. A value saved for one never reaches the other.

Overrides are validated before they are written. A threshold set to nonsense (gap_min
above gap_max, a negative price floor) would not raise anywhere useful — it would just
silently produce zero candidates forever, which looks exactly like a quiet market.
"""

import logging
from dataclasses import replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.models.scanner_settings import SETTINGS_ROW_ID, ScannerSettings
from app.services.scanner.profiles import ThresholdProfile, available_profiles, get_profile

logger = logging.getLogger(__name__)

# Threshold fields a user may override. Deliberately not every ThresholdProfile field:
# `name` and `description` are identity, not configuration.
OVERRIDABLE_FIELDS = (
    "float_max",
    "avg_volume_min",
    "gap_min",
    "gap_max",
    "rvol_min",
    "upside_min",
    "price_floor",
    "dollar_volume_min",
)

INT_FIELDS = {"float_max"}


class InvalidThresholdOverrideError(ValueError):
    """An override was rejected before it could silently break every scan."""


def validate_overrides(overrides: dict[str, Any]) -> dict[str, float | int]:
    """Coerce and sanity-check user-supplied overrides."""
    cleaned: dict[str, float | int] = {}

    for key, value in (overrides or {}).items():
        if key not in OVERRIDABLE_FIELDS:
            raise InvalidThresholdOverrideError(
                f"Unknown threshold {key!r}. Overridable: {', '.join(OVERRIDABLE_FIELDS)}"
            )
        if value is None:
            continue
        try:
            number = int(value) if key in INT_FIELDS else float(value)
        except (TypeError, ValueError) as exc:
            raise InvalidThresholdOverrideError(f"{key} must be a number, got {value!r}") from exc
        if number < 0:
            raise InvalidThresholdOverrideError(f"{key} cannot be negative (got {number})")
        cleaned[key] = number

    gap_min = cleaned.get("gap_min")
    gap_max = cleaned.get("gap_max")
    if gap_min is not None and gap_max is not None and gap_min > gap_max:
        raise InvalidThresholdOverrideError(
            f"gap_min ({gap_min}) cannot exceed gap_max ({gap_max}) — that band matches "
            f"nothing, which would look like a quiet market rather than a misconfiguration."
        )

    return cleaned


def validate_profile_name(name: str | None) -> str | None:
    if name is None:
        return None
    resolved = name.strip().lower()
    if resolved not in available_profiles():
        raise InvalidThresholdOverrideError(
            f"Unknown profile {name!r}; expected one of {available_profiles()}"
        )
    return resolved


class ScannerSettingsStore:
    """Reads and writes the singleton settings row."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        if session_factory is None:
            from app.core.database import async_session_maker

            session_factory = async_session_maker
        self._session_factory = session_factory

    async def load(self) -> ScannerSettings | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(ScannerSettings).where(ScannerSettings.id == SETTINGS_ROW_ID)
            )

    async def get_all_overrides(self) -> dict[str, dict[str, Any]]:
        """Every profile's overrides, keyed by profile name."""
        row = await self.load()
        if row is None or not row.overrides_json:
            return {}
        return {
            name: dict(values)
            for name, values in row.overrides_json.items()
            if isinstance(values, dict)
        }

    async def get_active_profile_name(self) -> str | None:
        """The stored profile selection, or None to fall back to `SCAN_PROFILE`."""
        row = await self.load()
        return row.profile if row is not None else None

    async def get_overrides(self, profile: str | None = None) -> tuple[str | None, dict[str, Any]]:
        """(active_profile_name, overrides for `profile`).

        `profile` defaults to whichever profile is currently active, so callers that
        just want "what is in effect" need not know the name.
        """
        row = await self.load()
        if row is None:
            return None, {}

        active = row.profile
        target = profile or active or get_settings().scan_profile
        all_overrides = await self.get_all_overrides()
        return active, dict(all_overrides.get(target, {}))

    async def save(
        self, profile: str | None = None, overrides: dict[str, Any] | None = None
    ) -> ScannerSettings:
        """Persist overrides SCOPED TO a profile, and select that profile.

        Overrides are written under the profile being edited — `profile` if given, else
        whichever is currently active. Other profiles' overrides are left untouched. See
        the module docstring for why they are not shared.
        """
        resolved_profile = validate_profile_name(profile)
        cleaned = validate_overrides(overrides or {})

        async with self._session_factory() as session:
            row = await session.scalar(
                select(ScannerSettings).where(ScannerSettings.id == SETTINGS_ROW_ID)
            )
            if row is None:
                row = ScannerSettings(id=SETTINGS_ROW_ID)
                session.add(row)

            target = resolved_profile or row.profile or get_settings().scan_profile
            stored = dict(row.overrides_json or {})
            if cleaned:
                stored[target] = cleaned
            else:
                stored.pop(target, None)

            row.profile = resolved_profile
            row.overrides_json = stored or None
            await session.commit()
            await session.refresh(row)

        logger.info(
            "Scanner settings updated: active profile=%s, overrides for %s=%s",
            resolved_profile,
            target,
            cleaned,
        )
        return row

    async def clear(self) -> None:
        """Drop EVERY profile's overrides and the profile selection."""
        async with self._session_factory() as session:
            row = await session.scalar(
                select(ScannerSettings).where(ScannerSettings.id == SETTINGS_ROW_ID)
            )
            if row is None:
                return
            row.profile = None
            row.overrides_json = None
            await session.commit()
        logger.info("Scanner settings cleared; thresholds fall back to the environment.")

    async def resolve_profile(self, name: str | None = None) -> ThresholdProfile:
        """Build the effective profile: env defaults, then that profile's stored overrides.

        `name` (an explicit per-run choice, e.g. `--profile demo`) wins over the stored
        selection, which in turn wins over `SCAN_PROFILE`.

        **Overrides are looked up by the resolved profile's own name.** A value saved
        while `production` was active never reaches `demo` — see the module docstring.
        """
        stored_profile = await self.get_active_profile_name()
        profile = get_profile(name or stored_profile)

        all_overrides = await self.get_all_overrides()
        applied = {
            k: v
            for k, v in all_overrides.get(profile.name, {}).items()
            if k in OVERRIDABLE_FIELDS
        }
        if not applied:
            return profile

        logger.info("Applying stored %s overrides: %s", profile.name, applied)
        return replace(profile, **applied)
