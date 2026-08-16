"""Incremental nightly rebuild of the pre-market volume profile.

Phase 4B claimed an incremental update and delivered a same-day skip: a *fresh* night still
re-fetched all 20 sessions per ticker, ~4x more work than needed. The claim was believed
because the figure quoted to support it — "5 calls, 9 seconds" — came from a same-day
re-run, which is a different thing.

So these tests count **calls**, per scenario, by name. The three the brief asks to be
distinguished are `test_a_fresh_night_costs_one_call`, `test_a_same_day_rerun_costs_nothing`
and `test_a_forced_rebuild_refetches_everything`.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, update

from app.models.premarket_session_volume import PremarketSessionVolume
from app.models.premarket_volume_profile import PremarketVolumeProfile
from app.models.universe import Universe
from app.services.bars import Bar
from app.services.reference.volume_profile import (
    STATUS_BUILT,
    STATUS_SKIPPED,
    VolumeProfileBuilder,
)

ET = ZoneInfo("America/New_York")
TICKER = "INCR"


class RecordingClient:
    """An FMP stand-in that serves a fixed session history and counts requests."""

    def __init__(self, sessions: dict[date, list[tuple[int, int, float]]]):
        self._sessions = sessions
        self.calls: list[tuple[date, date]] = []

    async def get_intraday_bars(self, ticker, interval, start, end, extended):
        self.calls.append((start, end))
        rows = []
        for day, bars in self._sessions.items():
            if start <= day <= end:
                for hour, minute, volume in bars:
                    rows.append(
                        type(
                            "Row",
                            (),
                            {
                                "date": datetime(day.year, day.month, day.day, hour, minute),
                                "volume": volume,
                                "close": 10.0,
                            },
                        )()
                    )
        return rows

    @property
    def call_count(self) -> int:
        return len(self.calls)


def history(days: list[date]) -> dict[date, list[tuple[int, int, float]]]:
    """A simple two-bar pre-market curve on each given session."""
    return {day: [(4, 0, 100.0), (4, 5, 50.0)] for day in days}


TRADING_DAYS = [date(2026, 8, d) for d in (3, 4, 5, 6, 7, 10, 11, 12, 13, 14)]


@pytest.fixture
async def seeded_universe(test_session_factory):
    async with test_session_factory() as session:
        session.add(Universe(ticker=TICKER, is_active=True, is_accessible_free_tier=True))
        await session.commit()


async def stored_sessions(session_factory) -> list[date]:
    async with session_factory() as session:
        rows = await session.scalars(
            select(PremarketSessionVolume.session_date).order_by(
                PremarketSessionVolume.session_date
            )
        )
        return list(rows)


async def build(session_factory, client, upto: date, force: bool = False):
    builder = VolumeProfileBuilder(
        client=client, session_factory=session_factory, force=force
    )
    return await builder.build_ticker(TICKER, upto=upto)


async def pretend_a_night_passed(session_factory) -> None:
    """Backdate `computed_at` so the same-day freshness check does not short-circuit.

    Every build in this file happens within one wall-clock second, but the scenario under
    test is consecutive NIGHTS. Without this the second build returns `skipped` and the
    test would be measuring the same-day path while claiming to measure the fresh one —
    which is precisely the mistake Phase 4B made when it reported "5 calls, 9 seconds".
    """
    yesterday = datetime.utcnow() - timedelta(days=1)
    async with session_factory() as session:
        await session.execute(update(PremarketVolumeProfile).values(computed_at=yesterday))
        await session.execute(update(PremarketSessionVolume).values(computed_at=yesterday))
        await session.commit()


# ------------------------------------------------------------------ the three figures


async def test_a_first_build_fetches_the_whole_window(
    test_session_factory, seeded_universe
):
    """With nothing stored, behaviour is unchanged from before: paginate back until the
    target is met. This is the cost the incremental path is measured against."""
    client = RecordingClient(history(TRADING_DAYS))

    result = await build(test_session_factory, client, upto=date(2026, 8, 14))

    assert result.status == STATUS_BUILT
    assert result.sessions == 10
    assert client.call_count >= 2, "a wide request is silently truncated; it must paginate"
    assert await stored_sessions(test_session_factory) == TRADING_DAYS


async def test_a_fresh_night_costs_one_call(test_session_factory, seeded_universe):
    """THE regression test for the Phase 4B claim.

    A night that already has yesterday's history should fetch only the new session — not
    re-fetch twenty."""
    first = RecordingClient(history(TRADING_DAYS))
    await build(test_session_factory, first, upto=date(2026, 8, 14))
    baseline = first.call_count
    await pretend_a_night_passed(test_session_factory)

    # The next trading day arrives.
    next_day = date(2026, 8, 17)
    second = RecordingClient(history(TRADING_DAYS + [next_day]))
    result = await build(test_session_factory, second, upto=next_day)

    assert result.status == STATUS_BUILT
    assert second.call_count == 1, (
        f"a fresh night must cost one request, not {baseline} — this is the bug 4B "
        f"reported as fixed while a full rebuild was still happening every night"
    )
    assert next_day in await stored_sessions(test_session_factory)
    # And the new session is actually IN the average, not merely stored.
    assert result.sessions == 11


async def test_a_same_day_rerun_costs_nothing(test_session_factory, seeded_universe):
    """The figure 4B mistook for incremental. Still correct, just a different scenario."""
    client = RecordingClient(history(TRADING_DAYS))
    await build(test_session_factory, client, upto=date(2026, 8, 14))
    calls_after_first = client.call_count

    result = await build(test_session_factory, client, upto=date(2026, 8, 14))

    assert result.status == STATUS_SKIPPED
    assert client.call_count == calls_after_first, "no requests at all on a same-day re-run"


async def test_a_forced_rebuild_refetches_everything(test_session_factory, seeded_universe):
    """`--rebuild` has to be a real reconstruction, or it is useless as an escape hatch
    when a profile is suspected of being wrong."""
    client = RecordingClient(history(TRADING_DAYS))
    await build(test_session_factory, client, upto=date(2026, 8, 14))
    incremental_calls = client.call_count

    rebuild = RecordingClient(history(TRADING_DAYS))
    result = await build(test_session_factory, rebuild, upto=date(2026, 8, 14), force=True)

    assert result.status == STATUS_BUILT
    assert rebuild.call_count == incremental_calls, "a full re-fetch, ignoring what is stored"
    assert result.sessions == 10


# ------------------------------------------------------------------ correctness


async def test_the_incremental_average_equals_a_full_rebuild(
    test_session_factory, seeded_universe
):
    """The whole risk of this change: a cheaper path that quietly computes something else.

    RVOL divides by this number, so a discrepancy would surface as confident wrong
    candidates rather than as an error.
    """
    next_day = date(2026, 8, 17)
    full_history = history(TRADING_DAYS + [next_day])

    # Incremental: build to the 14th, then add the 17th.
    await build(test_session_factory, RecordingClient(history(TRADING_DAYS)),
                upto=date(2026, 8, 14))
    await pretend_a_night_passed(test_session_factory)
    await build(test_session_factory, RecordingClient(full_history), upto=next_day)

    async with test_session_factory() as session:
        incremental = {
            row.bucket_minute: row.avg_cumulative_volume
            for row in await session.scalars(select(PremarketVolumeProfile))
        }

    # Full rebuild of the same window, from scratch.
    await build(test_session_factory, RecordingClient(full_history), upto=next_day, force=True)

    async with test_session_factory() as session:
        rebuilt = {
            row.bucket_minute: row.avg_cumulative_volume
            for row in await session.scalars(select(PremarketVolumeProfile))
        }

    assert incremental == rebuilt


async def test_sessions_outside_the_window_are_dropped(
    test_session_factory, seeded_universe, monkeypatch
):
    """"Drop the oldest" is the half that stops the table growing without bound."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "profile_sessions_target", 3)

    client = RecordingClient(history(TRADING_DAYS))
    result = await build(test_session_factory, client, upto=date(2026, 8, 14))

    assert result.sessions == 3
    kept = await stored_sessions(test_session_factory)
    assert kept == TRADING_DAYS[-3:], "only the newest three survive the prune"


async def test_sessions_sampled_stays_accurate_after_an_incremental_update(
    test_session_factory, seeded_universe
):
    """`sessions_sampled` is what downstream code uses to decide whether a profile is
    trustworthy. An incremental update that leaves it stale would keep a profile looking
    thin — or worse, looking complete when it is not."""
    await build(test_session_factory, RecordingClient(history(TRADING_DAYS[:4])),
                upto=TRADING_DAYS[3])

    async with test_session_factory() as session:
        first = await session.scalar(select(PremarketVolumeProfile.sessions_sampled))
    assert first == 4
    await pretend_a_night_passed(test_session_factory)

    await build(test_session_factory, RecordingClient(history(TRADING_DAYS)),
                upto=TRADING_DAYS[-1])

    async with test_session_factory() as session:
        after = {row.sessions_sampled for row in await session.scalars(
            select(PremarketVolumeProfile)
        )}
    assert after == {10}, "every bucket row carries the updated count"


async def test_a_short_history_is_not_re_probed_every_night(
    test_session_factory, seeded_universe
):
    """A young ticker has fewer sessions than the target and always will. Probing
    backwards each night to rediscover that costs real calls forever — measured at 5 per
    ticker per night in the first draft of this change. `--rebuild` is the repair path."""
    early = TRADING_DAYS[-3:]
    await build(test_session_factory, RecordingClient(history(early)), upto=early[-1])
    assert len(await stored_sessions(test_session_factory)) == 3
    await pretend_a_night_passed(test_session_factory)

    next_day = date(2026, 8, 17)
    client = RecordingClient(history(TRADING_DAYS + [next_day]))
    result = await build(test_session_factory, client, upto=next_day)

    assert client.call_count == 1, "forward only — no backward re-probing"
    assert result.sessions == 4, "it grows from the front, one session a night"

    # And --rebuild is what refills it when that is actually wanted.
    rebuilt = RecordingClient(history(TRADING_DAYS + [next_day]))
    forced = await build(test_session_factory, rebuilt, upto=next_day, force=True)
    assert forced.sessions == 11


async def test_json_bucket_keys_survive_the_round_trip(
    test_session_factory, seeded_universe
):
    """JSON object keys are strings. A profile keyed by "0" instead of 0 would never match
    a live bucket lookup, and RVOL would silently fall back or divide by nothing."""
    await build(test_session_factory, RecordingClient(history(TRADING_DAYS)),
                upto=date(2026, 8, 14))

    async with test_session_factory() as session:
        row = await session.scalar(select(PremarketSessionVolume))

    assert set(row.buckets) == {"0", "5"}, "stored as strings, as JSON requires"
    assert row.bucket_map() == {0: 100.0, 5: 150.0}, "read back as integers"


async def test_a_bar_added_to_an_existing_session_updates_it(
    test_session_factory, seeded_universe
):
    """Re-fetching a session that is already stored must converge on the new curve rather
    than colliding on the unique constraint — two nightly runs can overlap on Render."""
    await build(test_session_factory, RecordingClient(history(TRADING_DAYS)),
                upto=date(2026, 8, 14))

    revised = history(TRADING_DAYS)
    revised[TRADING_DAYS[-1]] = [(4, 0, 500.0)]
    await build(test_session_factory, RecordingClient(revised),
                upto=date(2026, 8, 14), force=True)

    async with test_session_factory() as session:
        row = await session.scalar(
            select(PremarketSessionVolume).where(
                PremarketSessionVolume.session_date == TRADING_DAYS[-1]
            )
        )

    assert row.bucket_map() == {0: 500.0}


async def test_a_regular_hours_only_session_is_stored_and_counted(
    test_session_factory, seeded_universe
):
    """It adds no buckets but it IS a session that was fetched. Dropping it would
    understate `sessions_sampled` and leave the forward cursor stuck on that day."""
    days = TRADING_DAYS[-2:]
    sessions = history(days)
    sessions[days[-1]] = [(11, 0, 5000.0)]  # regular hours only

    result = await build(test_session_factory, RecordingClient(sessions), upto=days[-1])

    assert result.sessions == 2, "counted, even though it contributes nothing"
    assert await stored_sessions(test_session_factory) == days

    async with test_session_factory() as session:
        row = await session.scalar(
            select(PremarketSessionVolume).where(
                PremarketSessionVolume.session_date == days[-1]
            )
        )
    assert row.bucket_map() == {}

    # And the cursor has advanced past it: the next night fetches forward, not back.
    await pretend_a_night_passed(test_session_factory)
    client = RecordingClient(sessions)
    await build(test_session_factory, client, upto=days[-1])
    assert client.call_count == 0, "nothing newer than the stored session to fetch"


def test_curves_from_bars_and_from_storage_reduce_identically():
    """The incremental average mixes freshly-fetched bars with stored curves. If the two
    were reduced differently, a session would change value simply by being stored."""
    builder = VolumeProfileBuilder(client=None, session_factory=lambda: None)
    day = date(2026, 8, 3)
    bars = {
        day: [
            Bar(start=datetime(2026, 8, 3, 4, 0, tzinfo=ET), volume=100.0),
            Bar(start=datetime(2026, 8, 3, 4, 5, tzinfo=ET), volume=50.0),
        ]
    }

    curves = builder.session_curves(bars)
    from_bars, _ = builder.average_profile(bars, target_sessions=20)
    from_storage, _ = builder.average_curves(curves, target_sessions=20)

    assert from_bars == from_storage
