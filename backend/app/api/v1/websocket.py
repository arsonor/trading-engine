"""WebSocket API endpoint.

One channel: `alerts`. The scanner pushes the session's candidate set over it after every
completed scan (`ScannerAlertService._broadcast`).

The per-symbol `market_data` channel was removed in Phase 3.5 with the Alpaca stream
manager. Nothing produced messages for it once the app became alerts-only, so it was a
subscription clients could make and never hear from. The wire protocol is otherwise
unchanged — `subscribe` / `unsubscribe` / `ping` behave exactly as before.
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Dict, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()

ALERTS_CHANNEL = "alerts"


class ConnectionManager:
    """Manages WebSocket connections and channel subscriptions."""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.subscriptions: Dict[str, Set[str]] = {ALERTS_CHANNEL: set()}

    async def connect(self, websocket: WebSocket) -> str:
        """Accept connection and return connection ID."""
        await websocket.accept()
        connection_id = str(uuid.uuid4())
        self.active_connections[connection_id] = websocket
        return connection_id

    def disconnect(self, connection_id: str) -> None:
        """Remove connection and all its subscriptions."""
        self.active_connections.pop(connection_id, None)
        for channel in self.subscriptions.values():
            channel.discard(connection_id)

    async def subscribe(self, connection_id: str, channel: str) -> None:
        """Subscribe to a channel. Unknown channels are ignored, not created."""
        if channel in self.subscriptions:
            self.subscriptions[channel].add(connection_id)

    def unsubscribe(self, connection_id: str, channel: str) -> None:
        """Unsubscribe from a channel."""
        if channel in self.subscriptions:
            self.subscriptions[channel].discard(connection_id)

    def get_subscriptions(self, connection_id: str) -> list[str]:
        """Channels this connection is subscribed to."""
        return [
            channel
            for channel, connections in self.subscriptions.items()
            if connection_id in connections
        ]

    async def send_personal(self, connection_id: str, message: dict) -> None:
        """Send message to a specific connection."""
        if connection_id in self.active_connections:
            try:
                await self.active_connections[connection_id].send_json(message)
            except Exception:
                self.disconnect(connection_id)

    async def broadcast_to_channel(self, channel: str, message: dict) -> None:
        """Broadcast to all subscribers of a channel."""
        if channel not in self.subscriptions:
            return

        disconnected = []
        for conn_id in self.subscriptions[channel]:
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
    """WebSocket endpoint for real-time scanner updates."""
    connection_id = await manager.connect(websocket)

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

                await manager.subscribe(connection_id, channel)
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
