"""
app/modules/orders/handlers.py

Event-driven handler for the `conversation.message_saved` event.

Why `conversation.message_saved` instead of `message.received`?
----------------------------------------------------------------
The conversation handler publishes `conversation.message_saved` AFTER its
database transaction commits. Subscribing to this event (rather than the
earlier `message.received` event) guarantees that the Conversation row is
already present in the database when `handle_order_intent` runs — eliminating
the race condition where `get_conversation_by_sender()` found nothing because
the conversation handler's transaction was still in flight.

Additionally, the payload already contains `conversation_id`, so no extra
database lookup is needed here.

MVP logic
---------
When a customer message contains an order-intent keyword ("order", "buy",
"purchase", etc.), an INQUIRY order is automatically created for their
conversation — unless an open order already exists (idempotency).

Wiring
------
Call register_order_intent_handler(tenant_id) in app/main.py's lifespan:

    from app.modules.orders.handlers import register_order_intent_handler

    @asynccontextmanager
    async def lifespan(app):
        ...
        task = register_order_intent_handler("tenant-uuid-here")
        yield
        task.cancel()
"""

import asyncio

from app.core.logging import get_logger
from app.infra.database import async_session_factory
from app.infra.event_bus import Event, create_global_listener_task
from app.modules.orders.service import OrderService

logger = get_logger(__name__)

_CONVERSATION_MESSAGE_SAVED_EVENT = "conversation.message_saved"

# Keywords that signal purchase intent (case-insensitive substring match)
_ORDER_KEYWORDS: frozenset[str] = frozenset(
    {"order", "buy", "purchase", "want", "get me", "i need", "checkout"}
)


def _has_order_intent(message: str) -> bool:
    """Return True if the message contains at least one order-intent keyword."""
    lowered = message.lower()
    return any(keyword in lowered for keyword in _ORDER_KEYWORDS)


async def handle_order_intent(event: Event) -> None:
    """
    Create an INQUIRY order when a conversation.message_saved event signals
    purchase intent.

    Steps:
    1. Extract and validate payload fields.
    2. Check for order-intent keywords — drop if none found.
    3. Open a DB session and call OrderService.create_order_from_conversation().
       conversation_id comes directly from the event payload — the conversation
       is guaranteed to be committed by the time this handler runs.
    4. The service handles the open-order idempotency check internally.
    5. Commit on success; the session context manager rolls back on any error.
    """
    payload = event.payload
    tenant_id: str = event.tenant_id
    conversation_id: str = payload.get("conversation_id", "")
    message: str = payload.get("message", "")

    if not (tenant_id and conversation_id and message):
        logger.debug(
            "Order handler: skipping event_id=%s — missing fields (tenant=%r)",
            event.event_id,
            tenant_id,
        )
        return

    if not _has_order_intent(message):
        logger.debug(
            "Order handler: no intent keywords in message event_id=%s", event.event_id
        )
        return

    sender: str = payload.get("sender", "")
    logger.info(
        "Order intent detected event_id=%s tenant=%s sender=%s",
        event.event_id,
        tenant_id,
        sender,
    )

    async with async_session_factory.begin() as session:
        svc = OrderService(session)
        order = await svc.create_order_from_conversation(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
        )

    if order is None:
        logger.info(
            "Order handler: open order already exists for conversation=%s — skipped",
            conversation_id,
        )
    else:
        logger.info(
            "Order handler: order created order_id=%s conversation=%s",
            order.id,
            conversation_id,
        )


def register_order_intent_handler() -> asyncio.Task:
    """
    Start a single background Task that consumes `conversation.message_saved`
    events from ALL tenants and creates INQUIRY orders on purchase intent.
    """
    logger.info("Registering order-intent handler (all tenants)")
    return create_global_listener_task(
        event_name=_CONVERSATION_MESSAGE_SAVED_EVENT,
        handler=handle_order_intent,
    )
