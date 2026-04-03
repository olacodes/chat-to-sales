"""
app/modules/realtime/service.py

Bridges the Redis event bus to the WebSocket connection manager.

How it works
------------
For each tenant registered at startup, a background asyncio Task is created
that pattern-subscribes to ALL events for that tenant:

    chattosales.events.<tenant_id>.*

When an event arrives it is translated into a client-facing WebSocket message
and broadcast to every connected WebSocket for that tenant via ConnectionManager.

Event → WebSocket message shape
--------------------------------
Every message sent to clients follows this envelope:

    {
        "event": "<EventName in PascalCase>",
        "tenant_id": "<tenant_id>",
        "event_id": "<uuid>",
        "timestamp": "<iso8601>",
        "data": { ...event-specific payload... }
    }

Internal event names (dot-notation) are converted to PascalCase for the
client-facing envelope to match common frontend conventions.

Wiring
------
Call register_realtime_listener(tenant_id) in main.py's lifespan for each
tenant that should receive real-time pushes:

    from app.modules.realtime.service import register_realtime_listener

    _listener_tasks.append(register_realtime_listener("tenant-abc-123"))
"""

import asyncio

from app.core.logging import get_logger
from app.infra.event_bus import Event, subscribe_tenant_events
from app.modules.realtime.manager import ConnectionManager

logger = get_logger(__name__)


def _to_pascal(event_name: str) -> str:
    """
    Convert dot-separated event name to PascalCase for the client envelope.

    Examples:
        "order.state_changed"  → "OrderStateChanged"
        "payment.confirmed"    → "PaymentConfirmed"
        "message.received"     → "MessageReceived"
    """
    return "".join(
        part.capitalize()
        for segment in event_name.split(".")
        for part in segment.split("_")
    )


async def _listen_and_broadcast(
    tenant_id: str,
    manager: ConnectionManager,
) -> None:
    """
    Long-running coroutine: consume all Redis events for a tenant and
    push them to connected WebSocket clients.

    Exits cleanly on asyncio.CancelledError (app shutdown).
    All other exceptions are logged and the loop continues so one bad
    event never kills the listener.
    """
    logger.info("Realtime listener started for tenant=%s", tenant_id)

    async for event in subscribe_tenant_events(tenant_id):
        try:
            message = {
                "event": _to_pascal(event.event_name),
                "tenant_id": event.tenant_id,
                "event_id": event.event_id,
                "timestamp": event.timestamp,
                "data": event.payload,
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
    tenant_id: str,
    manager: ConnectionManager,
) -> asyncio.Task:
    """
    Spawn a background task that forwards all Redis events for tenant_id
    to connected WebSocket clients via the given ConnectionManager.

    Returns the task so the caller can cancel it on shutdown.
    """
    task = asyncio.ensure_future(_listen_and_broadcast(tenant_id, manager))
    logger.info("Realtime listener task created for tenant=%s", tenant_id)
    return task
