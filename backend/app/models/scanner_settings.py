"""Runtime scanner settings — threshold overrides editable without a redeploy.

`docs/CLAUDE.md` section 5 suggested repurposing the v1 `rules` table for tunable
thresholds. That table stores free-text `config_yaml`, so thresholds would end up as
unvalidated strings inside a text column belonging to a retired subsystem. A dedicated
single-row table keeps them typed, validated and independent of the v1 rule engine's
eventual removal.

Layering: environment variables are the defaults, this row overrides them, and an absent
row means "use the environment". That way a fresh deploy works with no seed data, and a
user edit survives a restart.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# The settings row is a singleton; this is its primary key.
SETTINGS_ROW_ID = 1


class ScannerSettings(Base):
    """Singleton row holding the user's threshold and profile overrides."""

    __tablename__ = "scanner_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=SETTINGS_ROW_ID)
    # Active threshold profile ("production" / "demo"). NULL means use SCAN_PROFILE.
    profile: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Per-threshold overrides, e.g. {"gap_min": 2.5}. Keys absent here fall back to env.
    overrides_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self) -> str:
        return f"<ScannerSettings(profile={self.profile}, overrides={self.overrides_json})>"
