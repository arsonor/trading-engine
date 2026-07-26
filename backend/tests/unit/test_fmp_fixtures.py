"""Tests for fixture recording and replay.

The replay client exists so CI never calls FMP. Its value depends entirely on it
behaving like the live client, which it does by overriding only the transport — these
tests pin that: the same errors come out of a replayed 403 as out of a live one.
"""

import json

import pytest

from app.services.fmp.client import EP_EOD_FULL, EP_SHARES_FLOAT
from app.services.fmp.errors import MalformedResponse, SymbolNotAvailable
from app.services.fmp.fixtures import (
    FixtureFmpClient,
    FixtureNotFound,
    FixtureStore,
    fixture_key,
)


def test_fixture_key_is_stable_and_order_independent():
    assert fixture_key("quote", {"symbol": "AAPL"}) == "quote__symbol=AAPL"
    assert fixture_key(EP_EOD_FULL, {"symbol": "AAPL"}) == (
        "historical-price-eod_full__symbol=AAPL"
    )
    assert fixture_key("batch-quote", {"b": "2", "a": "1"}) == fixture_key(
        "batch-quote", {"a": "1", "b": "2"}
    )


def test_fixture_key_never_includes_the_api_key():
    """Recordings are committed to the repo; the key must not travel with them."""
    key = fixture_key("quote", {"symbol": "AAPL", "apikey": "super-secret"})
    assert "secret" not in key
    assert key == "quote__symbol=AAPL"


def test_long_keys_are_hashed_not_truncated_into_collisions(tmp_path):
    many = ",".join(f"SYM{i:04d}" for i in range(60))
    other = ",".join(f"SYM{i:04d}" for i in range(1, 61))

    assert fixture_key("batch-quote", {"symbols": many}) != fixture_key(
        "batch-quote", {"symbols": other}
    )


def test_save_and_load_round_trip(tmp_path):
    store = FixtureStore(tmp_path)
    path = store.save("quote", {"symbol": "AAPL"}, 200, [{"symbol": "AAPL", "price": 1.0}])

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["status"] == 200
    assert "recorded_at" in document
    assert "apikey" not in document["params"]

    raw = store.load("quote", {"symbol": "AAPL"})
    assert raw.status == 200
    assert raw.payload[0]["symbol"] == "AAPL"


def test_missing_fixture_says_how_to_record_it(tmp_path):
    store = FixtureStore(tmp_path)
    with pytest.raises(FixtureNotFound, match="record_fmp_fixtures"):
        store.load("quote", {"symbol": "NOPE"})


async def test_replay_client_parses_like_the_live_client(fixture_fmp_client):
    bars = await fixture_fmp_client.get_eod_history("AAPL")

    assert len(bars) == 260
    assert str(bars[0].date) == "2026-07-24"  # newest first, as from the live client
    assert bars[0].close > bars[-1].close


async def test_replay_client_reproduces_a_restricted_symbol(fixture_fmp_client):
    """A recorded 403 raises the same typed error the live path would raise."""
    with pytest.raises(SymbolNotAvailable):
        await fixture_fmp_client.get_eod_history("SNDL")


async def test_replay_client_reproduces_an_empty_response(fixture_fmp_client):
    with pytest.raises(SymbolNotAvailable):
        await fixture_fmp_client.get_eod_history("EMPTY")


async def test_replay_client_reproduces_a_malformed_response(fixture_fmp_client):
    with pytest.raises(MalformedResponse):
        await fixture_fmp_client.get_eod_history("BROKEN")


async def test_replay_client_spends_no_budget(fixture_fmp_client):
    await fixture_fmp_client.get_eod_history("AAPL")

    assert fixture_fmp_client.budget.is_enabled is False
    assert await fixture_fmp_client.budget.calls_used_today() == 0


async def test_replay_client_handles_missing_float_figures(fixture_fmp_client):
    shares = await fixture_fmp_client.get_shares_float("NOFLT")

    assert shares.symbol == "NOFLT"
    assert shares.float_shares is None


def test_store_lists_recorded_keys(fmp_fixture_store):
    keys = fmp_fixture_store.keys()

    assert f"{EP_EOD_FULL.replace('/', '_')}__symbol=AAPL" in keys
    assert f"{EP_SHARES_FLOAT}__symbol=AAPL" in keys


async def test_fixture_client_defaults_to_the_configured_directory():
    """Constructing without a store must not explode — it reads FMP_FIXTURES_DIR."""
    client = FixtureFmpClient()
    assert client.store.root.name == "fmp"
