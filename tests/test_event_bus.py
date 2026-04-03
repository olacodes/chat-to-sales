"""
tests/test_event_bus.py

Unit tests for the Redis Pub/Sub event bus.
Redis is mocked — no live connection required.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.infra.event_bus import Event, _channel, _pattern, publish_event


# ── Event dataclass ───────────────────────────────────────────────────────────


def test_event_channel_format():
    event = Event(
        event_name="order.created",
        tenant_id="tenant-123",
        payload={"order_id": "abc"},
    )
    assert event.channel == "chattosales.events.tenant-123.order.created"


def test_event_round_trip_json():
    event = Event(
        event_name="payment.success",
        tenant_id="tenant-456",
        payload={"amount": 5000},
    )
    restored = Event.from_json(event.to_json())
    assert restored.event_name == event.event_name
    assert restored.tenant_id == event.tenant_id
    assert restored.payload == event.payload
    assert restored.event_id == event.event_id
    assert restored.timestamp == event.timestamp


def test_event_auto_fields_populated():
    event = Event(event_name="x", tenant_id="t", payload={})
    assert event.event_id  # non-empty
    assert event.timestamp  # non-empty ISO string


def test_channel_helper():
    assert _channel("t1", "order.created") == "chattosales.events.t1.order.created"


def test_pattern_helper():
    assert _pattern("t1") == "chattosales.events.t1.*"


# ── publish_event ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_event_calls_redis_publish():
    event = Event(
        event_name="order.created",
        tenant_id="tenant-abc",
        payload={"order_id": "xyz"},
    )

    mock_redis = AsyncMock()
    mock_redis.publish = AsyncMock(return_value=1)

    with patch("app.infra.event_bus.get_redis", return_value=mock_redis):
        receivers = await publish_event(event)

    mock_redis.publish.assert_awaited_once_with(event.channel, event.to_json())
    assert receivers == 1


@pytest.mark.asyncio
async def test_publish_event_returns_zero_when_no_subscribers():
    event = Event(event_name="order.created", tenant_id="t", payload={})

    mock_redis = AsyncMock()
    mock_redis.publish = AsyncMock(return_value=0)

    with patch("app.infra.event_bus.get_redis", return_value=mock_redis):
        receivers = await publish_event(event)

    assert receivers == 0
