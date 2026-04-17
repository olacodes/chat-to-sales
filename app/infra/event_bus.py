"""
app/infra/event_bus.py

Lightweight Redis Pub/Sub event bus for ChatToSales MVP.

Design notes
------------
- Each event is published to a channel named:
      chattosales.events.<tenant_id>.<event_name>
  This makes it trivial to subscribe per-tenant, per-event, or with a
  wildcard pattern (PSUBSCRIBE chattosales.events.<tenant_id>.*).

- A separate Redis connection is created for each subscriber because a
  connection in pub/sub mode can only issue subscription commands.
  The publisher reuses the shared pool from infra/cache.py.

- publish_event() is fire-and-forget by design (MVP). Delivery is
  best-effort: if no subscriber is listening the message is dropped.
  Upgrade path: swap for Redis Streams (see bottom of file) when you need
  persistence, consumer groups, or at-least-once delivery.

- subscribe_event() is an async generator. Use it inside a background
  asyncio task (see example at the bottom of this module).
"""

import asyncio
import json
from collections.abc import AsyncGenerator
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine
from uuid import uuid4

import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.logging import get_logger
from app.infra.cache import get_redis

logger = get_logger(__name__)
_settings = get_settings()

# ── Channel helpers ───────────────────────────────────────────────────────────

_CHANNEL_PREFIX = "chattosales.events"


def _channel(tenant_id: str, event_name: str) -> str:
    """Return the canonical pub/sub channel name for an event."""
    return f"{_CHANNEL_PREFIX}.{tenant_id}.{event_name}"


def _pattern(tenant_id: str) -> str:
    """Return a wildcard pattern matching all events for a tenant."""
    return f"{_CHANNEL_PREFIX}.{tenant_id}.*"


def _global_pattern(event_name: str) -> str:
    """
    Return a PSUBSCRIBE pattern that matches a specific event across ALL tenants.

    Example: _global_pattern("message.received")
             → "chattosales.events.*.message.received"

    The '*' matches any tenant-id segment. UUID-style tenant IDs never contain
    dots, so this pattern will not over-match.
    """
    return f"{_CHANNEL_PREFIX}.*.{event_name}"


# All events, all tenants — used by the realtime broadcaster
_ALL_EVENTS_PATTERN = f"{_CHANNEL_PREFIX}.*"


# ── Event schema ──────────────────────────────────────────────────────────────


@dataclass
class Event:
    """
    Canonical event envelope published on the bus.

    Fields
    ------
    event_name : str
        Dot-separated, lower-snake name, e.g. "order.created".
    tenant_id  : str
        UUID of the owning tenant — used to route to the correct channel.
    payload    : dict
        Arbitrary JSON-serialisable data specific to the event type.
    event_id   : str
        Auto-generated UUID v4; useful for deduplication in consumers.
    timestamp  : str
        ISO-8601 UTC string set at creation time.
    """

    event_name: str
    tenant_id: str
    payload: dict[str, Any]
    event_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "Event":
        data = json.loads(raw)
        return cls(**data)

    @property
    def channel(self) -> str:
        return _channel(self.tenant_id, self.event_name)


# ── Publisher ─────────────────────────────────────────────────────────────────


async def publish_event(event: Event) -> int:
    """
    Publish an event to its tenant-scoped channel.

    Returns the number of active subscribers that received the message.
    Zero is normal if no subscriber is currently listening (pub/sub is
    ephemeral — use Redis Streams for durable delivery).
    """
    redis = get_redis()
    receivers: int = await redis.publish(event.channel, event.to_json())
    logger.debug(
        "Published event=%s tenant=%s channel=%s receivers=%d",
        event.event_name,
        event.tenant_id,
        event.channel,
        receivers,
    )
    return receivers


# ── Subscriber ────────────────────────────────────────────────────────────────


async def subscribe_event(
    tenant_id: str,
    event_name: str,
) -> AsyncGenerator[Event, None]:
    """
    Async generator that yields Events published to a specific channel.

    A dedicated Redis connection is created for the subscriber so the
    shared pool remains usable for regular commands.

    Usage (inside a background task)
    ---------------------------------
        async for event in subscribe_event("tenant-uuid", "order.created"):
            await handle_order_created(event)

    The generator exits cleanly when the enclosing task is cancelled.
    """
    channel = _channel(tenant_id, event_name)
    client: aioredis.Redis = aioredis.from_url(
        _settings.redis_url_str,
        encoding="utf-8",
        decode_responses=True,
    )
    pubsub = client.pubsub()

    try:
        await pubsub.subscribe(channel)
        logger.info("Subscribed to channel: %s", channel)

        async for message in pubsub.listen():
            if message["type"] != "message":
                # Skip 'subscribe' confirmation messages
                continue
            try:
                yield Event.from_json(message["data"])
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning("Malformed event on channel %s: %s", channel, exc)

    except asyncio.CancelledError:
        logger.info("Subscription cancelled for channel: %s", channel)
        raise
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
        await client.aclose()


async def subscribe_tenant_events(
    tenant_id: str,
) -> AsyncGenerator[Event, None]:
    """
    Async generator that yields ALL events for a tenant via pattern subscribe.

    Use this when a consumer needs to react to multiple event types from one
    tenant (e.g. a notification fanout service).
    """
    pattern = _pattern(tenant_id)
    client: aioredis.Redis = aioredis.from_url(
        _settings.redis_url_str,
        encoding="utf-8",
        decode_responses=True,
    )
    pubsub = client.pubsub()

    try:
        await pubsub.psubscribe(pattern)
        logger.info("Pattern-subscribed to: %s", pattern)

        async for message in pubsub.listen():
            if message["type"] != "pmessage":
                continue
            try:
                yield Event.from_json(message["data"])
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning("Malformed event on pattern %s: %s", pattern, exc)

    except asyncio.CancelledError:
        logger.info("Pattern subscription cancelled: %s", pattern)
        raise
    finally:
        await pubsub.punsubscribe(pattern)
        await pubsub.aclose()
        await client.aclose()


async def subscribe_all_tenants_event(
    event_name: str,
) -> AsyncGenerator[Event, None]:
    """
    Async generator that yields events with a specific name from ALL tenants.

    Uses Redis PSUBSCRIBE on 'chattosales.events.*.{event_name}' so a single
    background task handles every tenant — including tenants created after
    startup — without any per-tenant registration.

    Usage (inside a background task)
    ---------------------------------
        async for event in subscribe_all_tenants_event("message.received"):
            await handle_message_received(event)
            # event.tenant_id tells you which tenant triggered it
    """
    pattern = _global_pattern(event_name)
    client: aioredis.Redis = aioredis.from_url(
        _settings.redis_url_str,
        encoding="utf-8",
        decode_responses=True,
    )
    pubsub = client.pubsub()

    try:
        await pubsub.psubscribe(pattern)
        logger.info("Global pattern-subscribed to: %s", pattern)

        async for message in pubsub.listen():
            if message["type"] != "pmessage":
                continue
            try:
                yield Event.from_json(message["data"])
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning("Malformed event on pattern %s: %s", pattern, exc)

    except asyncio.CancelledError:
        logger.info("Global pattern subscription cancelled: %s", pattern)
        raise
    finally:
        await pubsub.punsubscribe(pattern)
        await pubsub.aclose()
        await client.aclose()


async def subscribe_all_events() -> AsyncGenerator[Event, None]:
    """
    Async generator that yields ALL events across ALL tenants.

    Subscribes to 'chattosales.events.*' — used by the realtime broadcaster
    which needs to forward every event to connected WebSocket clients regardless
    of which tenant produced it.
    """
    pattern = _ALL_EVENTS_PATTERN
    client: aioredis.Redis = aioredis.from_url(
        _settings.redis_url_str,
        encoding="utf-8",
        decode_responses=True,
    )
    pubsub = client.pubsub()

    try:
        await pubsub.psubscribe(pattern)
        logger.info("All-events pattern-subscribed to: %s", pattern)

        async for message in pubsub.listen():
            if message["type"] != "pmessage":
                continue
            try:
                yield Event.from_json(message["data"])
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning("Malformed event on pattern %s: %s", pattern, exc)

    except asyncio.CancelledError:
        logger.info("All-events pattern subscription cancelled: %s", pattern)
        raise
    finally:
        await pubsub.punsubscribe(pattern)
        await pubsub.aclose()
        await client.aclose()


Handler = Callable[[Event], Coroutine[Any, Any, None]]


def create_listener_task(
    tenant_id: str,
    event_name: str,
    handler: Handler,
) -> asyncio.Task:
    """
    Convenience wrapper that spawns a long-running asyncio Task for a handler.

    The task is automatically cancelled on application shutdown because
    FastAPI's lifespan cancels all pending tasks when the app stops.

    Usage (in lifespan or module startup)
    --------------------------------------
        from app.infra.event_bus import create_listener_task

        task = create_listener_task(
            tenant_id="*",          # wildcard not supported; pass real tenant
            event_name="order.created",
            handler=handle_order_created,
        )
    """

    async def _loop() -> None:
        async for event in subscribe_event(tenant_id, event_name):
            try:
                await handler(event)
            except Exception as exc:
                # Log and continue — never crash the listener loop
                logger.exception(
                    "Handler error for event=%s: %s", event.event_name, exc
                )

    task = asyncio.ensure_future(_loop())
    logger.info("Listener task created for tenant=%s event=%s", tenant_id, event_name)
    return task


def create_global_listener_task(
    event_name: str,
    handler: Handler,
) -> asyncio.Task:
    """
    Spawn a single long-running Task that consumes a specific event from
    ALL tenants via PSUBSCRIBE.

    Prefer this over create_listener_task() in production so that events from
    any tenant — including tenants registered after app startup — are handled
    automatically without restarting the application.
    """

    async def _loop() -> None:
        async for event in subscribe_all_tenants_event(event_name):
            try:
                await handler(event)
            except Exception as exc:
                logger.exception(
                    "Handler error for event=%s tenant=%s: %s",
                    event.event_name,
                    event.tenant_id,
                    exc,
                )

    task = asyncio.ensure_future(_loop())
    logger.info("Global listener task created for event=%s (all tenants)", event_name)
    return task


# ── EXAMPLE USAGE (not executed — reference only) ────────────────────────────
#
# Publishing:
# -----------
#   from app.infra.event_bus import Event, publish_event
#
#   event = Event(
#       event_name="order.created",
#       tenant_id="b1a2c3d4-...",
#       payload={"order_id": "...", "total": 4500},
#   )
#   await publish_event(event)
#
#
# Subscribing (in a background task):
# ------------------------------------
#   from app.infra.event_bus import subscribe_event
#
#   async def listen():
#       async for event in subscribe_event("b1a2c3d4-...", "order.created"):
#           print(event.payload)
#
#   asyncio.create_task(listen())
#
#
# Using the task helper:
# ----------------------
#   from app.infra.event_bus import create_listener_task
#
#   async def on_order_created(event: Event) -> None:
#       await send_confirmation_message(event.payload["order_id"])
#
#   create_listener_task("b1a2c3d4-...", "order.created", on_order_created)
