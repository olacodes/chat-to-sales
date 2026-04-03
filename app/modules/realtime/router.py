"""
app/modules/realtime/router.py

WebSocket endpoint: /ws/{tenant_id}

A client connects once per tenant and receives a stream of JSON messages
whenever a system event is published on the Redis bus for that tenant.

Connection lifecycle
---------------------
1. Client opens  ws://host/ws/<tenant_id>
2. Server calls  manager.connect()  — accepts the handshake and registers.
3. Server enters a receive loop, waiting for client messages or close frames.
   The receive loop keeps the connection alive and detects client disconnects.
4. On disconnect (WebSocketDisconnect or any network error) the connection is
   removed from the manager and the loop exits cleanly.

The manager is a module-level singleton shared across all requests.  The
realtime service spawns one background task per tenant at startup that
pattern-subscribes to all Redis events and calls manager.broadcast() — no
per-connection subscriptions are needed.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.logging import get_logger
from app.modules.realtime.manager import ConnectionManager

logger = get_logger(__name__)

router = APIRouter(tags=["Realtime"])

# Singleton shared with the background listener tasks in service.py
manager = ConnectionManager()


@router.websocket("/ws/{tenant_id}")
async def websocket_endpoint(tenant_id: str, websocket: WebSocket) -> None:
    """
    WebSocket endpoint for real-time event streaming.

    Clients connect to /ws/{tenant_id} and receive a JSON message for every
    system event published for that tenant.

    Message shape:
        {
            "event":     "OrderStateChanged",   ← PascalCase event name
            "tenant_id": "tenant-abc-123",
            "event_id":  "<uuid>",
            "timestamp": "<iso8601>",
            "data":      { ...event payload... }
        }
    """
    await manager.connect(tenant_id, websocket)
    try:
        while True:
            # Block here waiting for a client message or close frame.
            # We don't act on client messages for now — this loop exists
            # solely to detect disconnections.
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected cleanly tenant=%s", tenant_id)
    except Exception as exc:
        logger.warning("WebSocket connection error tenant=%s: %s", tenant_id, exc)
    finally:
        manager.disconnect(tenant_id, websocket)
