"""Runtime threshold overrides.

`docs/CLAUDE.md` calls for thresholds tunable *without a redeploy*, because the end
user's strategy will evolve and a deploy cycle is not an acceptable price for changing a
number. Environment variables alone cannot do that: changing one restarts the service.

Three layers, most specific wins:

    env defaults (SCAN_*)  ->  scanner_settings row  ->  explicit per-run argument

An absent row means "use the environment", so a fresh deploy needs no seed data. Only
keys the user actually changed are stored, so a later change to an env default still
reaches anything the user has not pinned.

Overrides are validated before they are written. A threshold set to nonsense (gap_min
above gap_max, a negative price floor) would not raise anywhere useful — it would just
silently produce zero candidates forever, which looks exactly like a quiet market.
"""

import logging
from dataclasses import replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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

    async def get_overrides(self) -> tuple[str | None, dict[str, Any]]:
        """(profile_name_override, threshold_overrides). Both may be empty."""
        row = await self.load()
        if row is None:
            return None, {}
        return row.profile, dict(row.overrides_json or {})

    async def save(
        self, profile: str | None = None, overrides: dict[str, Any] | None = None
    ) -> ScannerSettings:
        """Persist overrides. Validates first — see the module docstring on why."""
        resolved_profile = validate_profile_name(profile)
        cleaned = validate_overrides(overrides or {})

        async with self._session_factory() as session:
            row = await session.scalar(
                select(ScannerSettings).where(ScannerSettings.id == SETTINGS_ROW_ID)
            )
            if row is None:
                row = ScannerSettings(id=SETTINGS_ROW_ID)
                session.add(row)

            row.profile = resolved_profile
            row.overrides_json = cleaned or None
            await session.commit()
            await session.refresh(row)

        logger.info(
            "Scanner settings updated: profile=%s overrides=%s", resolved_profile, cleaned
        )
        return row

    async def clear(self) -> None:
        """Drop all overrides and fall back to the environment."""
        await self.save(profile=None, overrides={})

    async def resolve_profile(self, name: str | None = None) -> ThresholdProfile:
        """Build the effective profile: env defaults, then stored overrides.

        `name` (an explicit per-run choice, e.g. `--profile demo`) wins over the stored
        profile, which in turn wins over `SCAN_PROFILE`.
        """
        stored_profile, overrides = await self.get_overrides()
        profile = get_profile(name or stored_profile)

        if not overrides:
            return profile

        applied = {k: v for k, v in overrides.items() if k in OVERRIDABLE_FIELDS}
        if not applied:
            return profile

        logger.info("Applying stored threshold overrides to %s: %s", profile.name, applied)
        return replace(profile, **applied)
