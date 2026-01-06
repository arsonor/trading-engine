"""Integration tests for WebSocket functionality."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.websocket import ConnectionManager, get_manager
from app.main import app


class TestConnectionManager:
    """Tests for ConnectionManager class."""

    @pytest.fixture
    def manager(self) -> ConnectionManager:
        """Create a fresh ConnectionManager for each test."""
        return ConnectionManager()

    @pytest.fixture
    def mock_websocket(self) -> AsyncMock:
        """Create a mock WebSocket."""
        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        ws.receive_text = AsyncMock()
        return ws

    @pytest.mark.asyncio
    async def test_connect(self, manager: ConnectionManager, mock_websocket: AsyncMock):
        """Test WebSocket connection."""
        connection_id = await manager.connect(mock_websocket)

        assert connection_id in manager.active_connections
        assert manager.active_connections[connection_id] == mock_websocket
        mock_websocket.accept.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect(self, manager: ConnectionManager, mock_websocket: AsyncMock):
        """Test WebSocket disconnection."""
        connection_id = await manager.connect(mock_websocket)
        assert connection_id in manager.active_connections

        manager.disconnect(connection_id)
        assert connection_id not in manager.active_connections

    @pytest.mark.asyncio
    async def test_disconnect_cleans_subscriptions(
        self, manager: ConnectionManager, mock_websocket: AsyncMock
    ):
        """Test disconnection removes all subscriptions."""
        connection_id = await manager.connect(mock_websocket)

        # Subscribe to channels
        with patch("app.api.v1.websocket.get_stream_manager"):
            await manager.subscribe(connection_id, "alerts")
            await manager.subscribe(connection_id, "market_data", ["AAPL"])

        # Verify subscriptions
        assert connection_id in manager.subscriptions["alerts"]

        # Disconnect
        manager.disconnect(connection_id)

        # Verify subscriptions are cleaned up
        assert connection_id not in manager.subscriptions["alerts"]
        assert connection_id not in manager.subscriptions["market_data"]

    @pytest.mark.asyncio
    async def test_subscribe_alerts(
        self, manager: ConnectionManager, mock_websocket: AsyncMock
    ):
        """Test subscribing to alerts channel."""
        connection_id = await manager.connect(mock_websocket)

        await manager.subscribe(connection_id, "alerts")

        assert connection_id in manager.subscriptions["alerts"]

    @pytest.mark.asyncio
    async def test_subscribe_market_data_with_symbols(
        self, manager: ConnectionManager, mock_websocket: AsyncMock
    ):
        """Test subscribing to market_data with symbols."""
        connection_id = await manager.connect(mock_websocket)

        with patch("app.api.v1.websocket.get_stream_manager") as mock_stream:
            mock_stream.return_value.subscribe = AsyncMock()
            await manager.subscribe(connection_id, "market_data", ["AAPL", "GOOGL"])

        assert connection_id in manager.subscriptions["market_data"]
        assert "AAPL" in manager.symbol_subscriptions
        assert "GOOGL" in manager.symbol_subscriptions
        assert connection_id in manager.symbol_subscriptions["AAPL"]
        assert connection_id in manager.symbol_subscriptions["GOOGL"]

    @pytest.mark.asyncio
    async def test_unsubscribe(self, manager: ConnectionManager, mock_websocket: AsyncMock):
        """Test unsubscribing from a channel."""
        connection_id = await manager.connect(mock_websocket)
        await manager.subscribe(connection_id, "alerts")
        assert connection_id in manager.subscriptions["alerts"]

        manager.unsubscribe(connection_id, "alerts")
        assert connection_id not in manager.subscriptions["alerts"]

    @pytest.mark.asyncio
    async def test_get_subscriptions(
        self, manager: ConnectionManager, mock_websocket: AsyncMock
    ):
        """Test getting active subscriptions."""
        connection_id = await manager.connect(mock_websocket)

        # No subscriptions initially
        subs = manager.get_subscriptions(connection_id)
        assert subs == []

        # Subscribe to alerts
        await manager.subscribe(connection_id, "alerts")
        subs = manager.get_subscriptions(connection_id)
        assert "alerts" in subs

        # Subscribe to market_data
        with patch("app.api.v1.websocket.get_stream_manager"):
            await manager.subscribe(connection_id, "market_data")
        subs = manager.get_subscriptions(connection_id)
        assert "alerts" in subs
        assert "market_data" in subs

    @pytest.mark.asyncio
    async def test_send_personal(
        self, manager: ConnectionManager, mock_websocket: AsyncMock
    ):
        """Test sending personal message."""
        connection_id = await manager.connect(mock_websocket)
        message = {"type": "test", "data": "hello"}

        await manager.send_personal(connection_id, message)

        mock_websocket.send_json.assert_called_once_with(message)

    @pytest.mark.asyncio
    async def test_send_personal_disconnects_on_error(
        self, manager: ConnectionManager, mock_websocket: AsyncMock
    ):
        """Test that send_personal disconnects client on error."""
        connection_id = await manager.connect(mock_websocket)
        mock_websocket.send_json.side_effect = Exception("Connection error")

        await manager.send_personal(connection_id, {"type": "test"})

        assert connection_id not in manager.active_connections

    @pytest.mark.asyncio
    async def test_broadcast_to_channel(
        self, manager: ConnectionManager, mock_websocket: AsyncMock
    ):
        """Test broadcasting to channel subscribers."""
        connection_id = await manager.connect(mock_websocket)
        await manager.subscribe(connection_id, "alerts")

        message = {"type": "alert", "data": {"symbol": "AAPL"}}
        await manager.broadcast_to_channel("alerts", message)

        mock_websocket.send_json.assert_called_with(message)

    @pytest.mark.asyncio
    async def test_broadcast_to_channel_multiple_clients(self, manager: ConnectionManager):
        """Test broadcasting to multiple channel subscribers."""
        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        ws1.send_json = AsyncMock()

        ws2 = AsyncMock()
        ws2.accept = AsyncMock()
        ws2.send_json = AsyncMock()

        conn_id1 = await manager.connect(ws1)
        conn_id2 = await manager.connect(ws2)

        await manager.subscribe(conn_id1, "alerts")
        await manager.subscribe(conn_id2, "alerts")

        message = {"type": "alert", "data": {"symbol": "AAPL"}}
        await manager.broadcast_to_channel("alerts", message)

        ws1.send_json.assert_called_with(message)
        ws2.send_json.assert_called_with(message)

    @pytest.mark.asyncio
    async def test_broadcast_to_channel_unsubscribed_not_reached(
        self, manager: ConnectionManager
    ):
        """Test that unsubscribed clients don't receive broadcasts."""
        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        ws1.send_json = AsyncMock()

        ws2 = AsyncMock()
        ws2.accept = AsyncMock()
        ws2.send_json = AsyncMock()

        conn_id1 = await manager.connect(ws1)
        conn_id2 = await manager.connect(ws2)

        # Only subscribe first client
        await manager.subscribe(conn_id1, "alerts")

        message = {"type": "alert", "data": {"symbol": "AAPL"}}
        await manager.broadcast_to_channel("alerts", message)

        ws1.send_json.assert_called_with(message)
        ws2.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_broadcast_to_symbol(
        self, manager: ConnectionManager, mock_websocket: AsyncMock
    ):
        """Test broadcasting to symbol subscribers."""
        connection_id = await manager.connect(mock_websocket)

        with patch("app.api.v1.websocket.get_stream_manager"):
            await manager.subscribe(connection_id, "market_data", ["AAPL"])

        message = {"type": "quote", "data": {"symbol": "AAPL", "price": 150.0}}
        await manager.broadcast_to_symbol("AAPL", message)

        mock_websocket.send_json.assert_called_with(message)

    @pytest.mark.asyncio
    async def test_broadcast_to_symbol_case_insensitive(
        self, manager: ConnectionManager, mock_websocket: AsyncMock
    ):
        """Test symbol broadcast is case insensitive."""
        connection_id = await manager.connect(mock_websocket)

        with patch("app.api.v1.websocket.get_stream_manager"):
            await manager.subscribe(connection_id, "market_data", ["AAPL"])

        message = {"type": "quote", "data": {"symbol": "AAPL", "price": 150.0}}
        await manager.broadcast_to_symbol("aapl", message)  # lowercase

        mock_websocket.send_json.assert_called_with(message)

    @pytest.mark.asyncio
    async def test_broadcast_cleans_up_disconnected_clients(
        self, manager: ConnectionManager
    ):
        """Test that broadcast cleans up disconnected clients."""
        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        ws1.send_json = AsyncMock()

        ws2 = AsyncMock()
        ws2.accept = AsyncMock()
        ws2.send_json = AsyncMock(side_effect=Exception("Disconnected"))

        conn_id1 = await manager.connect(ws1)
        conn_id2 = await manager.connect(ws2)

        await manager.subscribe(conn_id1, "alerts")
        await manager.subscribe(conn_id2, "alerts")

        message = {"type": "alert", "data": {}}
        await manager.broadcast_to_channel("alerts", message)

        # ws2 should be disconnected due to error
        assert conn_id1 in manager.active_connections
        assert conn_id2 not in manager.active_connections


class TestWebSocketEndpoint:
    """Integration tests for WebSocket endpoint."""

    @pytest.fixture
    def anyio_backend(self):
        return "asyncio"

    @pytest.mark.asyncio
    async def test_websocket_connection(self, client: AsyncClient):
        """Test WebSocket connection and initial status message."""
        from starlette.testclient import TestClient

        with TestClient(app) as test_client:
            with test_client.websocket_connect("/api/v1/ws") as websocket:
                # Should receive initial status message
                data = websocket.receive_json()
                assert data["type"] == "status"
                assert data["data"]["connected"] is True
                assert "connection_id" in data["data"]
                assert data["data"]["subscriptions"] == []

    @pytest.mark.asyncio
    async def test_websocket_subscribe(self, client: AsyncClient):
        """Test subscribing to a channel."""
        from starlette.testclient import TestClient

        with TestClient(app) as test_client:
            with test_client.websocket_connect("/api/v1/ws") as websocket:
                # Receive initial status
                websocket.receive_json()

                # Subscribe to alerts
                websocket.send_json({"action": "subscribe", "channel": "alerts"})

                # Should receive subscription confirmation
                data = websocket.receive_json()
                assert data["type"] == "status"
                assert data["data"]["subscribed"] == "alerts"
                assert "alerts" in data["data"]["subscriptions"]

    @pytest.mark.asyncio
    async def test_websocket_unsubscribe(self, client: AsyncClient):
        """Test unsubscribing from a channel."""
        from starlette.testclient import TestClient

        with TestClient(app) as test_client:
            with test_client.websocket_connect("/api/v1/ws") as websocket:
                websocket.receive_json()  # Initial status

                # Subscribe
                websocket.send_json({"action": "subscribe", "channel": "alerts"})
                websocket.receive_json()  # Subscription confirmation

                # Unsubscribe
                websocket.send_json({"action": "unsubscribe", "channel": "alerts"})

                data = websocket.receive_json()
                assert data["type"] == "status"
                assert data["data"]["unsubscribed"] == "alerts"
                assert "alerts" not in data["data"]["subscriptions"]

    @pytest.mark.asyncio
    async def test_websocket_ping_pong(self, client: AsyncClient):
        """Test ping/pong functionality."""
        from starlette.testclient import TestClient

        with TestClient(app) as test_client:
            with test_client.websocket_connect("/api/v1/ws") as websocket:
                websocket.receive_json()  # Initial status

                # Send ping
                websocket.send_json({"action": "ping"})

                # Should receive pong
                data = websocket.receive_json()
                assert data["type"] == "pong"
                assert "timestamp" in data["data"]

    @pytest.mark.asyncio
    async def test_websocket_invalid_json(self, client: AsyncClient):
        """Test handling of invalid JSON."""
        from starlette.testclient import TestClient

        with TestClient(app) as test_client:
            with test_client.websocket_connect("/api/v1/ws") as websocket:
                websocket.receive_json()  # Initial status

                # Send invalid JSON
                websocket.send_text("not valid json{")

                # Should receive error
                data = websocket.receive_json()
                assert data["type"] == "error"
                assert data["data"]["code"] == "INVALID_JSON"

    @pytest.mark.asyncio
    async def test_websocket_unknown_action(self, client: AsyncClient):
        """Test handling of unknown action."""
        from starlette.testclient import TestClient

        with TestClient(app) as test_client:
            with test_client.websocket_connect("/api/v1/ws") as websocket:
                websocket.receive_json()  # Initial status

                # Send unknown action
                websocket.send_json({"action": "unknown_action"})

                # Should receive error
                data = websocket.receive_json()
                assert data["type"] == "error"
                assert data["data"]["code"] == "UNKNOWN_ACTION"

    @pytest.mark.asyncio
    async def test_websocket_subscribe_missing_channel(self, client: AsyncClient):
        """Test subscribe without channel."""
        from starlette.testclient import TestClient

        with TestClient(app) as test_client:
            with test_client.websocket_connect("/api/v1/ws") as websocket:
                websocket.receive_json()  # Initial status

                # Subscribe without channel
                websocket.send_json({"action": "subscribe"})

                # Should receive error
                data = websocket.receive_json()
                assert data["type"] == "error"
                assert data["data"]["code"] == "MISSING_CHANNEL"

    @pytest.mark.asyncio
    async def test_websocket_subscribe_with_symbols(self, client: AsyncClient):
        """Test subscribing to market_data with symbols."""
        from starlette.testclient import TestClient

        with patch("app.api.v1.websocket.get_stream_manager") as mock_stream:
            mock_stream.return_value.subscribe = AsyncMock()

            with TestClient(app) as test_client:
                with test_client.websocket_connect("/api/v1/ws") as websocket:
                    websocket.receive_json()  # Initial status

                    # Subscribe with symbols
                    websocket.send_json({
                        "action": "subscribe",
                        "channel": "market_data",
                        "symbols": ["AAPL", "GOOGL"],
                    })

                    data = websocket.receive_json()
                    assert data["type"] == "status"
                    assert "market_data" in data["data"]["subscriptions"]


class TestGetManager:
    """Tests for get_manager function."""

    def test_get_manager_returns_singleton(self):
        """Test that get_manager returns the same instance."""
        manager1 = get_manager()
        manager2 = get_manager()
        assert manager1 is manager2
