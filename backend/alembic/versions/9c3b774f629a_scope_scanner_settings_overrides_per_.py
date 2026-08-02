"""Scope scanner settings overrides per profile

Revision ID: 9c3b774f629a
Revises: dbdf5784db31
Create Date: 2026-08-02 20:46:43.771368

"""

import json
import logging
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9c3b774f629a'
down_revision: Union[str, Sequence[str], None] = 'dbdf5784db31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

# Profile assumed for existing flat overrides when no profile was selected. `production`
# matches the SCAN_PROFILE default, so this preserves the behaviour those overrides had.
DEFAULT_PROFILE = "production"

# Fields the settings store accepts. Used to tell a flat override set from an
# already-scoped one without importing app code into the migration.
KNOWN_FIELDS = {
    "float_max",
    "avg_volume_min",
    "gap_min",
    "gap_max",
    "rvol_min",
    "upside_min",
    "price_floor",
    "dollar_volume_min",
}


def _load(raw) -> dict:
    if raw is None:
        return {}
    return json.loads(raw) if isinstance(raw, str) else dict(raw)


def _is_flat(overrides: dict) -> bool:
    """True when the payload is `{field: value}` rather than `{profile: {field: value}}`."""
    return any(key in KNOWN_FIELDS for key in overrides)


def upgrade() -> None:
    """Reshape `scanner_settings.overrides_json` from flat to profile-keyed.

    ## The bug this closes

    Overrides were a single flat set applied on top of whichever profile was active. The
    demo profile exists for exactly one reason — loosen the float cap so free-tier
    mega-caps reach Stage 1 — so a user saving thresholds while thinking in production
    terms silently reverted that cap. The scan then reported "0 candidates, successful
    scan, quiet market": the exact confusion the scan-status design exists to prevent.

    Demo and production are different regimes and no longer share an override set::

        before: {"gap_min": 2.5}
        after:  {"production": {"gap_min": 2.5}}

    ## Why the column shape rather than a table per profile

    A row per profile is the more conventional model, but the active-profile selection
    would then need its own home, splitting one small concept across two tables for a
    handful of numbers. Keeping the singleton row leaves each column with one meaning —
    `profile` is the active selection, `overrides_json` is every profile's overrides —
    and the reshape is reversible. The enforcement that matters (a stored override cannot
    reach another profile) lives in `settings_store.py` and its tests either way.

    ## Data

    Existing flat overrides are moved under the profile that was active when they were
    saved, or `production` when none was selected — preserving exactly the behaviour they
    had. Nothing is discarded. Already-scoped payloads are left alone, so this is safe to
    re-run.
    """
    bind = op.get_bind()

    rows = bind.execute(
        sa.text("SELECT id, profile, overrides_json FROM scanner_settings")
    ).fetchall()

    for row in rows:
        overrides = _load(row.overrides_json)
        if not overrides or not _is_flat(overrides):
            continue

        target = row.profile or DEFAULT_PROFILE
        bind.execute(
            sa.text("UPDATE scanner_settings SET overrides_json = :payload WHERE id = :id"),
            {"payload": json.dumps({target: overrides}), "id": row.id},
        )
        logger.info(
            "Scoped %s existing threshold override(s) to profile '%s': %s",
            len(overrides),
            target,
            ", ".join(sorted(overrides)),
        )


def downgrade() -> None:
    """Flatten back to a single override set.

    **This is lossy when more than one profile has overrides**, because the old shape
    could only hold one set. The active profile's overrides are kept and the others are
    dropped, with a warning naming what was discarded — that is the only choice that
    preserves current behaviour, since the active profile's values are the ones in
    effect.
    """
    bind = op.get_bind()

    rows = bind.execute(
        sa.text("SELECT id, profile, overrides_json FROM scanner_settings")
    ).fetchall()

    for row in rows:
        overrides = _load(row.overrides_json)
        if not overrides or _is_flat(overrides):
            continue

        target = row.profile or DEFAULT_PROFILE
        kept = overrides.get(target, {})
        dropped = sorted(name for name in overrides if name != target and overrides[name])

        if dropped:
            logger.warning(
                "Flattening scanner settings: keeping '%s' overrides, DISCARDING those "
                "for %s. The pre-scoping shape cannot represent more than one profile.",
                target,
                ", ".join(dropped),
            )

        bind.execute(
            sa.text("UPDATE scanner_settings SET overrides_json = :payload WHERE id = :id"),
            {"payload": json.dumps(kept) if kept else None, "id": row.id},
        )
