"""
app/modules/conversation/handlers.py

Event handler for `message.received` events published by the ingestion module.

Flow
----
1. A MessageReceived event arrives on the Redis pub/sub bus.
2. handle_message_received() is called by the listener task.
3. The payload is validated for required fields; malformed events are logged
   and dropped rather than crashing the listener loop.
4. A fresh AsyncSession is created (outside any HTTP request context).
5. ConversationService.handle_inbound() get-or-creates the conversation,
   persists the message, and commits the transaction.
6. Duplicate messages (same external_id on the same conversation) are
   silently dropped — the service returns None for the message.

Wiring
------
Call register_message_received_handler(tenant_id) in app/main.py's lifespan
for each tenant that should have conversations persisted:

    from app.modules.conversation.handlers import register_message_received_handler

    @asynccontextmanager
    async def lifespan(app):
        ...
        task = register_message_received_handler("tenant-uuid-here")
        yield
        task.cancel()

For dynamic multi-tenant systems, fetch active tenant IDs from the database
at startup and register one listener task per tenant.
"""

import asyncio

from app.core.logging import get_logger
from app.infra.database import async_session_factory
from app.infra.event_bus import Event, create_global_listener_task, publish_event
from app.modules.conversation.service import ConversationService

logger = get_logger(__name__)

_MESSAGE_RECEIVED_EVENT = "message.received"
_CONVERSATION_MESSAGE_SAVED_EVENT = "conversation.message_saved"


async def handle_message_received(event: Event) -> None:
    """
    Persist conversation + message for a single MessageReceived event.

    The handler owns its own DB session so it operates completely outside
    of any HTTP request lifecycle. The session is committed inside
    ConversationService.handle_inbound() and closed by the context manager.
    """
    payload = event.payload
    tenant_id: str = event.tenant_id
    channel: str = payload.get("channel", "")
    # Accept both new and legacy key names for rollback safety
    sender_id: str = payload.get("sender_identifier") or payload.get("sender", "")
    content: str = payload.get("message", "")
    # Try both field names — ingestion service may populate either
    external_id: str | None = payload.get("message_id") or payload.get("external_id")

    if not (tenant_id and channel and sender_id and content):
        logger.warning(
            "Dropping malformed message.received event_id=%s — "
            "tenant_id=%r channel=%r sender=%r content_len=%d",
            event.event_id,
            tenant_id,
            channel,
            sender_id,
            len(content),
        )
        return

    async with async_session_factory.begin() as session:
        svc = ConversationService(session)
        conv, msg = await svc.handle_inbound(
            tenant_id=tenant_id,
            channel=channel,
            sender_id=sender_id,
            content=content,
            external_id=external_id,
        )

    if msg is None:
        logger.info(
            "Duplicate message dropped event_id=%s conversation_id=%s",
            event.event_id,
            conv.id,
        )
    else:
        logger.info(
            "Message persisted event_id=%s conversation_id=%s message_id=%s",
            event.event_id,
            conv.id,
            msg.id,
        )
        # Publish AFTER the transaction has committed so the order handler (and
        # any other downstream subscriber) is guaranteed to see the conversation
        # row in the database when it processes this event.
        await publish_event(
            Event(
                event_name=_CONVERSATION_MESSAGE_SAVED_EVENT,
                tenant_id=tenant_id,
                payload={
                    # Full message fields — lets the frontend update its cache
                    # directly without an extra API round-trip.
                    "id": str(msg.id),
                    "conversation_id": str(conv.id),
                    "sender_role": msg.sender_role,
                    "sender_identifier": sender_id,
                    "content": content,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                    # Conversation / routing context
                    "tenant_id": tenant_id,
                    "channel": channel,
                    "customer_identifier": sender_id,
                },
            )
        )


def register_message_received_handler() -> asyncio.Task:
    """
    Start a single background Task that consumes `message.received` events
    from ALL tenants and persists conversations to the database.

    Uses Redis PSUBSCRIBE so events from any tenant — including tenants
    created after app startup — are handled without restarting.
    """
    logger.info("Registering message.received handler (all tenants)")
    return create_global_listener_task(
        event_name=_MESSAGE_RECEIVED_EVENT,
        handler=handle_message_received,
    )
