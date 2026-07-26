"""Scanner-level errors.

`FeatureRequiresIntraday` is re-exported here so scanner code does not have to reach into
the FMP package for the tier-gating error it raises most often.
"""

from app.services.fmp.errors import FeatureRequiresIntraday

__all__ = ["FeatureRequiresIntraday", "InsufficientRvolData", "ScannerError"]


class ScannerError(Exception):
    """Base class for scanner failures."""


class InsufficientRvolData(ScannerError):
    """RVOL cannot be computed because a required input is missing or zero.

    Distinct from "RVOL is low": a ticker with no 20-day average volume must be skipped,
    never treated as a 0% relative-volume candidate.
    """
