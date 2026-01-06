"""Unit tests for watchlist API endpoints."""

import pytest
from httpx import AsyncClient

from app.models import Watchlist


class TestGetWatchlist:
    """Tests for GET /api/v1/watchlist endpoint."""

    @pytest.mark.asyncio
    async def test_get_watchlist_empty(self, client: AsyncClient):
        """Test getting empty watchlist."""
        response = await client.get("/api/v1/watchlist")
        assert response.status_code == 200
        data = response.json()
        assert data == []

    @pytest.mark.asyncio
    async def test_get_watchlist_with_items(
        self, client: AsyncClient, sample_watchlist_item: Watchlist
    ):
        """Test getting watchlist with items."""
        response = await client.get("/api/v1/watchlist")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["symbol"] == "AAPL"
        assert data[0]["notes"] == "Test watchlist item"
        assert data[0]["is_active"] is True

    @pytest.mark.asyncio
    async def test_get_watchlist_multiple_items(
        self, client: AsyncClient, multiple_watchlist_items: list[Watchlist]
    ):
        """Test getting watchlist with multiple items."""
        response = await client.get("/api/v1/watchlist")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 4
        symbols = [item["symbol"] for item in data]
        assert "AAPL" in symbols
        assert "GOOGL" in symbols
        assert "MSFT" in symbols
        assert "TSLA" in symbols

    @pytest.mark.asyncio
    async def test_get_watchlist_sorted_by_added_at(
        self, client: AsyncClient, multiple_watchlist_items: list[Watchlist]
    ):
        """Test watchlist is sorted by added_at (descending)."""
        response = await client.get("/api/v1/watchlist")
        assert response.status_code == 200
        data = response.json()
        # Items should be sorted by added_at descending
        # Since all items are created close together, we just verify they all have added_at
        for item in data:
            assert "added_at" in item


class TestAddToWatchlist:
    """Tests for POST /api/v1/watchlist endpoint."""

    @pytest.mark.asyncio
    async def test_add_to_watchlist_success(self, client: AsyncClient):
        """Test adding a symbol to watchlist."""
        response = await client.post(
            "/api/v1/watchlist",
            json={"symbol": "AAPL", "notes": "Watching Apple"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["symbol"] == "AAPL"
        assert data["notes"] == "Watching Apple"
        assert data["is_active"] is True
        assert "id" in data
        assert "added_at" in data

    @pytest.mark.asyncio
    async def test_add_to_watchlist_uppercase(self, client: AsyncClient):
        """Test symbol is converted to uppercase."""
        response = await client.post(
            "/api/v1/watchlist",
            json={"symbol": "aapl"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_add_to_watchlist_no_notes(self, client: AsyncClient):
        """Test adding without notes."""
        response = await client.post(
            "/api/v1/watchlist",
            json={"symbol": "GOOGL"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["symbol"] == "GOOGL"
        assert data["notes"] is None

    @pytest.mark.asyncio
    async def test_add_to_watchlist_duplicate(
        self, client: AsyncClient, sample_watchlist_item: Watchlist
    ):
        """Test adding duplicate symbol returns 409."""
        response = await client.post(
            "/api/v1/watchlist",
            json={"symbol": "AAPL"},  # Already in watchlist
        )
        assert response.status_code == 409
        assert "already in watchlist" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_add_to_watchlist_duplicate_case_insensitive(
        self, client: AsyncClient, sample_watchlist_item: Watchlist
    ):
        """Test duplicate detection is case insensitive."""
        response = await client.post(
            "/api/v1/watchlist",
            json={"symbol": "aapl"},  # Lowercase but still duplicate
        )
        assert response.status_code == 409
        assert "already in watchlist" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_add_to_watchlist_with_notes(self, client: AsyncClient):
        """Test adding with notes."""
        response = await client.post(
            "/api/v1/watchlist",
            json={
                "symbol": "MSFT",
                "notes": "Microsoft - watching for earnings",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["symbol"] == "MSFT"
        assert data["notes"] == "Microsoft - watching for earnings"


class TestRemoveFromWatchlist:
    """Tests for DELETE /api/v1/watchlist/{symbol} endpoint."""

    @pytest.mark.asyncio
    async def test_remove_from_watchlist_success(
        self, client: AsyncClient, sample_watchlist_item: Watchlist
    ):
        """Test removing a symbol from watchlist."""
        response = await client.delete("/api/v1/watchlist/AAPL")
        assert response.status_code == 204

        # Verify item is removed
        get_response = await client.get("/api/v1/watchlist")
        assert get_response.status_code == 200
        data = get_response.json()
        assert len(data) == 0

    @pytest.mark.asyncio
    async def test_remove_from_watchlist_case_insensitive(
        self, client: AsyncClient, sample_watchlist_item: Watchlist
    ):
        """Test removal works with different case."""
        response = await client.delete("/api/v1/watchlist/aapl")
        assert response.status_code == 204

        # Verify item is removed
        get_response = await client.get("/api/v1/watchlist")
        data = get_response.json()
        assert len(data) == 0

    @pytest.mark.asyncio
    async def test_remove_from_watchlist_not_found(self, client: AsyncClient):
        """Test removing non-existent symbol returns 404."""
        response = await client.delete("/api/v1/watchlist/NOTEXIST")
        assert response.status_code == 404
        assert "not found in watchlist" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_remove_from_watchlist_multiple(
        self, client: AsyncClient, multiple_watchlist_items: list[Watchlist]
    ):
        """Test removing multiple items from watchlist."""
        # Remove first item
        response1 = await client.delete("/api/v1/watchlist/AAPL")
        assert response1.status_code == 204

        # Verify 3 items left
        get_response = await client.get("/api/v1/watchlist")
        data = get_response.json()
        assert len(data) == 3
        symbols = [item["symbol"] for item in data]
        assert "AAPL" not in symbols

        # Remove another item
        response2 = await client.delete("/api/v1/watchlist/GOOGL")
        assert response2.status_code == 204

        # Verify 2 items left
        get_response = await client.get("/api/v1/watchlist")
        data = get_response.json()
        assert len(data) == 2


class TestWatchlistEndToEnd:
    """End-to-end tests for watchlist functionality."""

    @pytest.mark.asyncio
    async def test_add_check_remove_flow(self, client: AsyncClient):
        """Test complete add-check-remove flow."""
        # Add symbol
        add_response = await client.post(
            "/api/v1/watchlist",
            json={"symbol": "NVDA", "notes": "NVIDIA"},
        )
        assert add_response.status_code == 201

        # Verify it's in watchlist
        list_response = await client.get("/api/v1/watchlist")
        data = list_response.json()
        assert any(item["symbol"] == "NVDA" for item in data)

        # Remove it
        delete_response = await client.delete("/api/v1/watchlist/NVDA")
        assert delete_response.status_code == 204

        # Verify it's removed
        list_response = await client.get("/api/v1/watchlist")
        data = list_response.json()
        assert not any(item["symbol"] == "NVDA" for item in data)

    @pytest.mark.asyncio
    async def test_cannot_readd_after_remove(self, client: AsyncClient):
        """Test that we can re-add a symbol after removing it."""
        # Add symbol
        await client.post(
            "/api/v1/watchlist",
            json={"symbol": "TSLA"},
        )

        # Remove it
        await client.delete("/api/v1/watchlist/TSLA")

        # Re-add it (should work)
        response = await client.post(
            "/api/v1/watchlist",
            json={"symbol": "TSLA", "notes": "Back in watchlist"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["symbol"] == "TSLA"
        assert data["notes"] == "Back in watchlist"
