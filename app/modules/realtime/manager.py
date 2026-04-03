"""
app/modules/realtime/manager.py

In-memory WebSocket connection registry.

Responsibilities:
- Track live WebSocket connections per tenant
- Broadcast JSON messages to all connections for a given tenant
- Handle disconnections safely without crashing

Design notes:
- Connections are stored in a dict[tenant_id → set[WebSocket]].
- A set is used (not a list) so that duplicate registrations are naturally
  prevented if the same WebSocket object is connected twice.
- broadcast() silently removes sockets that raise on send; this covers the
  case where the client disconnects mid-broadcast without going through the
  normal disconnect path.
- This manager is a plain Python object — no dependency on FastAPI or Redis.
  It is instantiated once as a module-level singleton in router.py.
"""

import json
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

from app.core.logging import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    """Thread-safe (within the asyncio event loop) WebSocket connection store."""

    def __init__(self) -> None:
        # tenant_id → set of active WebSocket connections
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self, tenant_id: str, websocket: WebSocket) -> None:
        """Accept the WebSocket handshake and register the connection."""
        await websocket.accept()
        self._connections[tenant_id].add(websocket)
        count = len(self._connections[tenant_id])
        logger.info(
            "WebSocket connected tenant=%s total_connections=%d",
            tenant_id,
            count,
        )

    def disconnect(self, tenant_id: str, websocket: WebSocket) -> None:
        """Remove a connection from the registry."""
        self._connections[tenant_id].discard(websocket)
        count = len(self._connections[tenant_id])
        logger.info(
            "WebSocket disconnected tenant=%s remaining_connections=%d",
            tenant_id,
            count,
        )
        # Clean up the key if the tenant has no more connections
        if count == 0:
            del self._connections[tenant_id]

    # ── Broadcast ─────────────────────────────────────────────────────────────

    async def broadcast(self, tenant_id: str, message: dict[str, Any]) -> None:
        """
        Send a JSON message to every connected client for the given tenant.

        Sockets that fail on send (client already gone) are removed silently
        so one bad connection never blocks the others.
        """
        sockets = list(self._connections.get(tenant_id, set()))
        if not sockets:
            return

        payload = json.dumps(message)
        stale: list[WebSocket] = []

        for ws in sockets:
            try:
                await ws.send_text(payload)
            except Exception:
                # Client disconnected without a clean close frame
                stale.append(ws)

        for ws in stale:
            self.disconnect(tenant_id, ws)

        delivered = len(sockets) - len(stale)
        if delivered:
            logger.debug(
                "Broadcast tenant=%s delivered=%d dropped=%d",
                tenant_id,
                delivered,
                len(stale),
            )

    # ── Introspection ─────────────────────────────────────────────────────────

    def count(self, tenant_id: str) -> int:
        """Return the number of active connections for a tenant."""
        return len(self._connections.get(tenant_id, set()))

    def active_tenants(self) -> list[str]:
        """Return all tenant IDs that currently have at least one connection."""
        return list(self._connections.keys())
