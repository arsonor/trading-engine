"""Services package.

Subpackages: `fmp` (market-data client + budget guard), `reference` (nightly EOD
metrics), `scanner` (the three-stage pipeline) and `alerts` (persistence + broadcast).
Nothing is re-exported here — the v1 Alpaca stream manager and rule-engine alert
generator that used to live at this level were removed in Phase 3.5.
"""
