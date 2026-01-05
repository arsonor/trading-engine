"""WebSocket API endpoint."""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Dict, Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.stream_manager import get_stream_manager

logger = logging.getLogger(__name__)
router = APIRouter()


class ConnectionManager:
    """Manages WebSocket connections and subscriptions."""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.subscriptions: Dict[str, Set[str]] = {
            "alerts": set(),
            "market_data": set(),
        }
        self.symbol_subscriptions: Dict[str, Set[str]] = {}  # symbol -> connection_ids

    async def connect(self, websocket: WebSocket) -> str:
        """Accept connection and return connection ID."""
        await websocket.accept()
        connection_id = str(uuid.uuid4())
        self.active_connections[connection_id] = websocket
        return connection_id

    def disconnect(self, connection_id: str) -> None:
        """Remove connection and all its subscriptions."""
        if connection_id in self.active_connections:
            del self.active_connections[connection_id]

        # Remove from channel subscriptions
        for channel in self.subscriptions.values():
            channel.discard(connection_id)

        # Remove from symbol subscriptions
        for symbol_subs in self.symbol_subscriptions.values():
            symbol_subs.discard(connection_id)

    async def subscribe(self, connection_id: str, channel: str, symbols: list[str] = None) -> None:
        """Subscribe to a channel."""
        if channel in self.subscriptions:
            self.subscriptions[channel].add(connection_id)

        if channel == "market_data" and symbols:
            new_symbols = []
            for symbol in symbols:
                symbol = symbol.upper()
                if symbol not in self.symbol_subscriptions:
                    self.symbol_subscriptions[symbol] = set()
                    new_symbols.append(symbol)
                self.symbol_subscriptions[symbol].add(connection_id)

            # Subscribe to Alpaca stream for new symbols
            if new_symbols:
                try:
                    stream_manager = get_stream_manager()
                    await stream_manager.subscribe(new_symbols)
                except Exception as e:
                    logger.error(f"Failed to subscribe to Alpaca stream: {e}")

    def unsubscribe(self, connection_id: str, channel: str) -> None:
        """Unsubscribe from a channel."""
        if channel in self.subscriptions:
            self.subscriptions[channel].discard(connection_id)

        # Remove from symbol subscriptions if market_data
        if channel == "market_data":
            for symbol_subs in self.symbol_subscriptions.values():
                symbol_subs.discard(connection_id)

    def get_subscriptions(self, connection_id: str) -> list[str]:
        """Get list of channels a connection is subscribed to."""
        subs = []
        for channel, connections in self.subscriptions.items():
            if connection_id in connections:
                subs.append(channel)
        return subs

    async def send_personal(self, connection_id: str, message: dict) -> None:
        """Send message to a specific connection."""
        if connection_id in self.active_connections:
            try:
                await self.active_connections[connection_id].send_json(message)
            except Exception:
                self.disconnect(connection_id)

    async def broadcast_to_channel(self, channel: str, message: dict) -> None:
        """Broadcast message to all subscribers of a channel."""
        if channel not in self.subscriptions:
            return

        disconnected = []
        for conn_id in self.subscriptions[channel]:
            if conn_id in self.active_connections:
                try:
                    await self.active_connections[conn_id].send_json(message)
                except Exception:
                    disconnected.append(conn_id)

        # Clean up disconnected clients
        for conn_id in disconnected:
            self.disconnect(conn_id)

    async def broadcast_to_symbol(self, symbol: str, message: dict) -> None:
        """Broadcast market data to subscribers of a specific symbol."""
        symbol = symbol.upper()
        if symbol not in self.symbol_subscriptions:
            return

        disconnected = []
        for conn_id in self.symbol_subscriptions[symbol]:
            if conn_id in self.active_connections:
                try:
                    await self.active_connections[conn_id].send_json(message)
                except Exception:
                    disconnected.append(conn_id)

        for conn_id in disconnected:
            self.disconnect(conn_id)


# Global connection manager instance
manager = ConnectionManager()


def get_manager() -> ConnectionManager:
    """Get the global connection manager."""
    return manager


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    connection_id = await manager.connect(websocket)

    # Send initial status
    await manager.send_personal(
        connection_id,
        {
            "type": "status",
            "data": {
                "connected": True,
                "connection_id": connection_id,
                "subscriptions": [],
            },
        },
    )

    try:
        while True:
            # Receive message
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
            except json.JSONDecodeError:
                await manager.send_personal(
                    connection_id,
                    {
                        "type": "error",
                        "data": {"code": "INVALID_JSON", "message": "Invalid JSON message"},
                    },
                )
                continue

            action = message.get("action")
            channel = message.get("channel")

            if action == "subscribe":
                if not channel:
                    await manager.send_personal(
                        connection_id,
                        {
                            "type": "error",
                            "data": {"code": "MISSING_CHANNEL", "message": "Channel is required"},
                        },
                    )
                    continue

                symbols = message.get("symbols", [])
                await manager.subscribe(connection_id, channel, symbols)

                await manager.send_personal(
                    connection_id,
                    {
                        "type": "status",
                        "data": {
                            "connected": True,
                            "subscribed": channel,
                            "subscriptions": manager.get_subscriptions(connection_id),
                        },
                    },
                )

            elif action == "unsubscribe":
                if channel:
                    manager.unsubscribe(connection_id, channel)

                await manager.send_personal(
                    connection_id,
                    {
                        "type": "status",
                        "data": {
                            "connected": True,
                            "unsubscribed": channel,
                            "subscriptions": manager.get_subscriptions(connection_id),
                        },
                    },
                )

            elif action == "ping":
                await manager.send_personal(
                    connection_id,
                    {
                        "type": "pong",
                        "data": {"timestamp": datetime.utcnow().isoformat()},
                    },
                )

            else:
                await manager.send_personal(
                    connection_id,
                    {
                        "type": "error",
                        "data": {
                            "code": "UNKNOWN_ACTION",
                            "message": f"Unknown action: {action}",
                        },
                    },
                )

    except WebSocketDisconnect:
        manager.disconnect(connection_id)
    except Exception as e:
        manager.disconnect(connection_id)
        raise e
