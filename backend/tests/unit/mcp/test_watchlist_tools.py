"""Unit tests for MCP watchlist tools."""

from unittest.mock import patch

import pytest

from app.models.watchlist import Watchlist


class TestGetWatchlist:
    """Tests for get_watchlist tool."""

    @pytest.mark.asyncio
    async def test_get_watchlist_with_items(
        self, mock_get_db_session, mcp_watchlist_items
    ):
        """Test getting watchlist with existing items."""
        with patch("app.mcp.tools.watchlist.get_db_session", mock_get_db_session):
            from app.mcp.tools.watchlist import get_watchlist

            result = await get_watchlist()

            assert "Watchlist" in result
            assert "4 symbols" in result
            assert "AAPL" in result
            assert "GOOGL" in result
            assert "MSFT" in result
            assert "Active" in result
            assert "Inactive" in result

    @pytest.mark.asyncio
    async def test_get_empty_watchlist(self, mock_get_db_session):
        """Test getting an empty watchlist."""
        with patch("app.mcp.tools.watchlist.get_db_session", mock_get_db_session):
            from app.mcp.tools.watchlist import get_watchlist

            result = await get_watchlist()

            assert "Watchlist" in result
            assert "empty" in result.lower()
            assert "add_to_watchlist" in result

    @pytest.mark.asyncio
    async def test_get_watchlist_shows_notes(
        self, mock_get_db_session, mcp_watchlist_items
    ):
        """Test that watchlist shows notes for items."""
        with patch("app.mcp.tools.watchlist.get_db_session", mock_get_db_session):
            from app.mcp.tools.watchlist import get_watchlist

            result = await get_watchlist()

            assert "Note:" in result
            assert "Tech giant" in result or "AI momentum" in result

    @pytest.mark.asyncio
    async def test_get_watchlist_shows_alert_counts(
        self, mock_get_db_session, mcp_watchlist_items, mcp_multiple_alerts
    ):
        """Test that watchlist shows alert counts per symbol."""
        with patch("app.mcp.tools.watchlist.get_db_session", mock_get_db_session):
            from app.mcp.tools.watchlist import get_watchlist

            result = await get_watchlist()

            assert "alert" in result.lower()

    @pytest.mark.asyncio
    async def test_get_watchlist_summary(
        self, mock_get_db_session, mcp_watchlist_items
    ):
        """Test that watchlist includes summary."""
        with patch("app.mcp.tools.watchlist.get_db_session", mock_get_db_session):
            from app.mcp.tools.watchlist import get_watchlist

            result = await get_watchlist()

            assert "Total:" in result
            assert "active" in result.lower()
            assert "inactive" in result.lower()


class TestAddToWatchlist:
    """Tests for add_to_watchlist tool."""

    @pytest.mark.asyncio
    async def test_add_new_symbol(self, mock_get_db_session):
        """Test adding a new symbol to watchlist."""
        with patch("app.mcp.tools.watchlist.get_db_session", mock_get_db_session):
            from app.mcp.tools.watchlist import add_to_watchlist

            result = await add_to_watchlist("NVDA")

            assert "Added to Watchlist" in result
            assert "NVDA" in result
            assert "Active" in result

    @pytest.mark.asyncio
    async def test_add_symbol_with_notes(self, mock_get_db_session):
        """Test adding a symbol with notes."""
        with patch("app.mcp.tools.watchlist.get_db_session", mock_get_db_session):
            from app.mcp.tools.watchlist import add_to_watchlist

            result = await add_to_watchlist("AMD", notes="GPU competitor to NVDA")

            assert "Added to Watchlist" in result
            assert "AMD" in result
            assert "GPU competitor" in result

    @pytest.mark.asyncio
    async def test_add_symbol_case_insensitive(self, mock_get_db_session):
        """Test that symbol is converted to uppercase."""
        with patch("app.mcp.tools.watchlist.get_db_session", mock_get_db_session):
            from app.mcp.tools.watchlist import add_to_watchlist

            result = await add_to_watchlist("nvda")

            assert "NVDA" in result

    @pytest.mark.asyncio
    async def test_add_duplicate_symbol(
        self, mock_get_db_session, mcp_watchlist_items
    ):
        """Test adding a symbol that already exists."""
        with patch("app.mcp.tools.watchlist.get_db_session", mock_get_db_session):
            from app.mcp.tools.watchlist import add_to_watchlist

            result = await add_to_watchlist("AAPL")

            assert "already in your watchlist" in result
            assert "AAPL" in result

    @pytest.mark.asyncio
    async def test_add_duplicate_shows_existing_info(
        self, mock_get_db_session, mcp_watchlist_items
    ):
        """Test that adding duplicate shows existing item info."""
        with patch("app.mcp.tools.watchlist.get_db_session", mock_get_db_session):
            from app.mcp.tools.watchlist import add_to_watchlist

            result = await add_to_watchlist("AAPL")

            assert "Added on:" in result
            assert "Notes:" in result


class TestRemoveFromWatchlist:
    """Tests for remove_from_watchlist tool."""

    @pytest.mark.asyncio
    async def test_remove_existing_symbol(
        self, mock_get_db_session, mcp_watchlist_items
    ):
        """Test removing an existing symbol."""
        with patch("app.mcp.tools.watchlist.get_db_session", mock_get_db_session):
            from app.mcp.tools.watchlist import remove_from_watchlist

            result = await remove_from_watchlist("AAPL")

            assert "Removed from Watchlist" in result
            assert "AAPL" in result
            assert "Was Added:" in result

    @pytest.mark.asyncio
    async def test_remove_symbol_case_insensitive(
        self, mock_get_db_session, mcp_watchlist_items
    ):
        """Test that removal is case insensitive."""
        with patch("app.mcp.tools.watchlist.get_db_session", mock_get_db_session):
            from app.mcp.tools.watchlist import remove_from_watchlist

            result = await remove_from_watchlist("aapl")

            assert "AAPL" in result
            assert "Removed" in result

    @pytest.mark.asyncio
    async def test_remove_nonexistent_symbol(self, mock_get_db_session):
        """Test removing a symbol that doesn't exist."""
        with patch("app.mcp.tools.watchlist.get_db_session", mock_get_db_session):
            from app.mcp.tools.watchlist import remove_from_watchlist

            result = await remove_from_watchlist("XYZ")

            assert "not in your watchlist" in result
            assert "XYZ" in result

    @pytest.mark.asyncio
    async def test_remove_shows_notes(
        self, mock_get_db_session, mcp_watchlist_items
    ):
        """Test that removal shows existing notes."""
        with patch("app.mcp.tools.watchlist.get_db_session", mock_get_db_session):
            from app.mcp.tools.watchlist import remove_from_watchlist

            result = await remove_from_watchlist("AAPL")

            assert "Notes:" in result

    @pytest.mark.asyncio
    async def test_remove_mentions_alerts(
        self, mock_get_db_session, mcp_watchlist_items, mcp_multiple_alerts
    ):
        """Test that removal mentions historical alerts."""
        with patch("app.mcp.tools.watchlist.get_db_session", mock_get_db_session):
            from app.mcp.tools.watchlist import remove_from_watchlist

            result = await remove_from_watchlist("AAPL")

            # Should mention alerts are preserved
            assert "alert" in result.lower()
            assert "preserved" in result or "historical" in result.lower()
