"""Universe size-change detection.

The universe size is discovered nightly, never configured. That is correct, but it means a
threshold edit in the dashboard can change how much work every scan pass does — with no
deploy, no error, and no symptom other than passes gradually failing to finish inside the
5-minute cadence. These checks are the only thing that makes such a change visible.

They warn; they never fail the build. A surprising universe is a thing to look at, not a
reason to leave the scanner with no data at all.
"""

from app.config import Settings
from app.services.reference.universe_builder import UniverseBuilder, UniverseReport


def builder(**overrides) -> UniverseBuilder:
    settings = Settings(
        database_url="postgresql+asyncpg://u:p@localhost:5432/db", **overrides
    )
    b = UniverseBuilder.__new__(UniverseBuilder)
    b._settings = settings
    return b


# ------------------------------------------------------------------ the ceiling


def test_ceiling_is_checked_against_the_scanned_set_not_the_maintained_one():
    """The distinction that stops this warning being noise.

    4A's ~3,500 figure is about per-pass bandwidth and the 5-minute cadence, which only the
    Stage-1 set consumes. The maintained universe costs one EOD call each per night and is
    expected to be several times larger — checking the ceiling against it would fire every
    single night and train the operator to ignore the warning.
    """
    b = builder(universe_size_ceiling=3_500)

    # Large maintained universe, small scanned set: no warning.
    assert b._size_warning(size=3_948, median=3_900, stage1=554) is None
    # Small maintained universe, oversized scanned set: warn.
    warning = b._size_warning(size=3_948, median=3_900, stage1=4_000)
    assert warning is not None
    assert "4,000" in warning and "clear Stage 1" in warning


def test_ceiling_warning_names_the_likely_cause():
    warning = builder(universe_size_ceiling=100)._size_warning(size=200, median=200, stage1=500)

    assert "threshold" in warning.lower()


def test_no_ceiling_warning_when_stage1_is_unknown():
    """Before the first reference_data refresh there is nothing to count, and guessing
    would produce a warning about a number that does not exist yet."""
    assert builder(universe_size_ceiling=10)._size_warning(
        size=5_000, median=None, stage1=None
    ) is None


# ------------------------------------------------------------------ material move


def test_no_warning_without_a_baseline():
    """The first ever build has no trailing median to move away from. It must not warn —
    a spurious first-run warning is exactly what makes people stop reading them."""
    assert builder()._size_warning(size=3_948, median=None, stage1=100) is None


def test_no_warning_for_ordinary_drift():
    assert builder(universe_size_move_pct=50.0)._size_warning(
        size=4_100, median=3_948, stage1=500
    ) is None


def test_warns_on_a_large_increase():
    warning = builder(universe_size_move_pct=50.0)._size_warning(
        size=8_000, median=4_000, stage1=500
    )

    assert warning is not None
    assert "grew" in warning and "100%" in warning


def test_warns_on_a_large_decrease():
    """A collapse matters as much as a spike: it means the scanner is quietly looking at
    a fraction of the market it looked at yesterday."""
    warning = builder(universe_size_move_pct=50.0)._size_warning(
        size=1_000, median=4_000, stage1=100
    )

    assert warning is not None
    assert "shrank" in warning and "75%" in warning


def test_move_threshold_is_boundary_inclusive():
    b = builder(universe_size_move_pct=50.0)

    assert b._size_warning(size=6_000, median=4_000, stage1=100) is not None  # exactly 50%
    assert b._size_warning(size=5_999, median=4_000, stage1=100) is None


def test_move_threshold_comes_from_config():
    b = builder(universe_size_move_pct=5.0)

    assert b._size_warning(size=4_400, median=4_000, stage1=100) is not None  # 10% > 5%


def test_ceiling_takes_precedence_over_a_move():
    """Both can be true at once; the ceiling is the one with an operational consequence,
    so it is the message the operator should see."""
    warning = builder(universe_size_ceiling=100, universe_size_move_pct=50.0)._size_warning(
        size=8_000, median=4_000, stage1=500
    )

    assert "clear Stage 1" in warning


# ------------------------------------------------------------------ report arithmetic


def test_dropped_by_float_cap_excludes_names_with_no_float_at_all():
    """A ticker with no float figure was not *rejected* by the cap — it was never
    assessable. Counting it as rejected would overstate how selective the cap is."""
    report = UniverseReport(screener_count=1_000, universe_size=600, without_float=150)

    assert report.dropped_by_float_cap == 250


def test_dropped_by_float_cap_never_goes_negative():
    report = UniverseReport(screener_count=10, universe_size=50, without_float=0)

    assert report.dropped_by_float_cap == 0
