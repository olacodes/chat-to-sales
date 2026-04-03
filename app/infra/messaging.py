"""
Event/message bus abstraction.

Publishes domain events to an AMQP broker (e.g. RabbitMQ) so modules remain
decoupled. Swap the implementation for Kafka / Redis Streams without changing
call sites.
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import aio_pika

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
_settings = get_settings()

_connection: aio_pika.abc.AbstractRobustConnection | None = None


@dataclass
class DomainEvent:
    event_type: str
    payload: dict[str, Any]
    event_id: str = ""
    occurred_at: str = ""

    def __post_init__(self) -> None:
        self.event_id = self.event_id or str(uuid4())
        self.occurred_at = self.occurred_at or datetime.now(timezone.utc).isoformat()


async def init_broker() -> None:
    global _connection
    try:
        _connection = await aio_pika.connect_robust(_settings.BROKER_URL)
        logger.info("Message broker connection established.")
    except Exception as exc:
        logger.warning(
            "Message broker unavailable — AMQP events will be dropped: %s", exc
        )
        _connection = None
    logger.info("Message broker connection established.")


async def close_broker() -> None:
    global _connection
    if _connection and not _connection.is_closed:
        await _connection.close()
        logger.info("Message broker connection closed.")


async def publish_event(exchange_name: str, event: DomainEvent) -> None:
    """Publish a domain event to the specified exchange."""
    if _connection is None or _connection.is_closed:
        logger.warning("Broker not connected — event dropped: %s", event.event_type)
        return

    async with _connection.channel() as channel:
        exchange = await channel.declare_exchange(
            exchange_name,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
        body = json.dumps(asdict(event)).encode()
        message = aio_pika.Message(
            body=body,
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await exchange.publish(message, routing_key=event.event_type)
        logger.debug("Published event: %s", event.event_type)
