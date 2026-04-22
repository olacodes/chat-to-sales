"""
app/modules/realtime/service.py

Bridges the Redis event bus to the WebSocket connection manager.

How it works
------------
A single background asyncio Task subscribes to ALL events across ALL tenants
via the pattern 'chattosales.events.*'. When an event arrives, the tenant_id
is read directly from the Event envelope and the message is broadcast to every
WebSocket connection registered for that tenant.

This means new tenants are handled automatically — no restart required.

Event → WebSocket message shape
--------------------------------
Every message sent to clients follows this envelope:

    {
        "type": "<event_name>",
        "payload": { ...event-specific payload... },
        "tenant_id": "<tenant_id>",
        "event_id": "<uuid>",
        "timestamp": "<iso8601>"
    }

Event names are kept in canonical dot-notation (e.g. "message.received")
so frontend listeners can match them directly without any name mapping.

Wiring
------
Call register_realtime_listener(manager) once in main.py's lifespan:

    from app.modules.realtime.service import register_realtime_listener

    _listener_tasks.append(register_realtime_listener(ws_manager))
"""

import asyncio

from app.core.logging import get_logger
from app.infra.event_bus import Event, subscribe_all_events
from app.modules.realtime.manager import ConnectionManager

logger = get_logger(__name__)


async def _listen_and_broadcast(
    manager: ConnectionManager,
) -> None:
    """
    Long-running coroutine: consume all Redis events across all tenants and
    push them to connected WebSocket clients.

    tenant_id is read from the Event envelope — no per-tenant startup wiring
    needed. Exits cleanly on asyncio.CancelledError (app shutdown).

    Envelope shape sent to clients:
        { "type": "<event_name>", "payload": {...}, "tenant_id": "...",
          "event_id": "...", "timestamp": "..." }

    Event names are kept in their canonical dot-notation form (e.g.
    "message.received") so frontend listeners can match them directly.
    """
    logger.info("Realtime listener started (all tenants)")

    async for event in subscribe_all_events():
        tenant_id = event.tenant_id
        try:
            message = {
                "type": event.event_name,
                "payload": event.payload,
                "tenant_id": tenant_id,
                "event_id": event.event_id,
                "timestamp": event.timestamp,
            }
            active = manager.count(tenant_id)
            if active:
                await manager.broadcast(tenant_id, message)
                logger.debug(
                    "Realtime broadcast event=%s tenant=%s clients=%d",
                    event.event_name,
                    tenant_id,
                    active,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "Realtime broadcast error event=%s tenant=%s: %s",
                event.event_name,
                tenant_id,
                exc,
            )


def register_realtime_listener(
    manager: ConnectionManager,
) -> asyncio.Task:
    """
    Spawn a single background task that forwards all Redis events for all
    tenants to connected WebSocket clients via the given ConnectionManager.

    Returns the task so the caller can cancel it on shutdown.
    """
    task = asyncio.ensure_future(_listen_and_broadcast(manager))
    logger.info("Realtime listener task created (all tenants)")
    return task
