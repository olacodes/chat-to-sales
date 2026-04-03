"""
app/modules/notifications/handlers.py

Event-driven notification handlers for the ChatToSales pipeline.

Each handler:
1. Extracts context from the event payload
2. Looks up the customer's phone number via conversation_id
3. Calls NotificationService.send_message() which persists the row,
   logs/dispatches the message, and marks it SENT or FAILED
4. Auto-commits via async_session_factory.begin()

Idempotency
-----------
The DB-level unique constraint on notifications.event_id ensures that even if
a Redis event is redelivered (e.g. after a crash-restart), the same message is
never sent twice.

Phone lookup strategy
---------------------
- order.created / order.state_changed  → payload includes conversation_id
  → ConversationRepository.get_conversation_by_id()
- payment.confirmed                    → payload has order_id, no conversation_id
  → OrderRepository.get_by_id() → order.conversation_id
  → ConversationRepository.get_conversation_by_id()

Wiring
------
Add to main.py lifespan:

    from app.modules.notifications.handlers import (
        register_order_created_notification_handler,
        register_order_state_changed_notification_handler,
        register_payment_confirmed_notification_handler,
    )

    _listener_tasks.append(register_order_created_notification_handler("tenant-abc-123"))
    _listener_tasks.append(register_order_state_changed_notification_handler("tenant-abc-123"))
    _listener_tasks.append(register_payment_confirmed_notification_handler("tenant-abc-123"))
"""

import asyncio

from app.core.logging import get_logger
from app.infra.database import async_session_factory
from app.infra.event_bus import Event, create_listener_task
from app.modules.conversation.repository import ConversationRepository
from app.modules.notifications.service import NotificationService
from app.modules.orders.models import OrderState
from app.modules.orders.repository import OrderRepository

logger = get_logger(__name__)

# ── Event name constants ──────────────────────────────────────────────────────

_EVT_ORDER_CREATED = "order.created"
_EVT_ORDER_STATE_CHANGED = "order.state_changed"
_EVT_PAYMENT_CONFIRMED = "payment.confirmed"

# ── Message templates ─────────────────────────────────────────────────────────

_MSG_ORDER_CREATED = (
    "Hi! Your order ({order_id_short}) has been created. " "Please confirm to proceed."
)
_MSG_ORDER_CONFIRMED = (
    "Your order ({order_id_short}) is confirmed! " "Please proceed to payment."
)
_MSG_ORDER_PAID = (
    "Payment received for order {order_id_short}. " "Your order is being processed."
)
_MSG_ORDER_COMPLETED = (
    "Your order ({order_id_short}) is completed. " "Thank you for shopping with us!"
)
_MSG_PAYMENT_CONFIRMED = (
    "Payment successful! Thank you for your purchase (order {order_id_short}). "
    "We'll keep you updated."
)


def _short_id(order_id: str) -> str:
    """Return the last 8 chars of a UUID for human-readable messages."""
    return order_id[-8:].upper()


# ── Phone lookup helpers ──────────────────────────────────────────────────────


async def _phone_from_conversation(
    session,
    conversation_id: str,
    tenant_id: str,
) -> str | None:
    """Return the customer phone number for a conversation, or None."""
    repo = ConversationRepository(session)
    conv = await repo.get_conversation_by_id(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
    )
    if conv is None:
        logger.warning(
            "Notification handler: conversation not found id=%s", conversation_id
        )
        return None
    return conv.phone_number


async def _phone_from_order(
    session,
    order_id: str,
    tenant_id: str,
) -> str | None:
    """Return the customer phone number by traversing order → conversation."""
    order_repo = OrderRepository(session)
    order = await order_repo.get_by_id(order_id=order_id, tenant_id=tenant_id)
    if order is None:
        logger.warning("Notification handler: order not found id=%s", order_id)
        return None
    return await _phone_from_conversation(session, order.conversation_id, tenant_id)


# ── Handlers ──────────────────────────────────────────────────────────────────


async def handle_order_created_notification(event: Event) -> None:
    """
    Send "Your order has been created" when an order.created event arrives.
    """
    payload = event.payload
    tenant_id: str = event.tenant_id
    order_id: str = payload.get("order_id", "")
    conversation_id: str = payload.get("conversation_id", "")

    if not (tenant_id and order_id and conversation_id):
        logger.warning(
            "order.created notification: missing fields event_id=%s — dropping",
            event.event_id,
        )
        return

    async with async_session_factory.begin() as session:
        phone = await _phone_from_conversation(session, conversation_id, tenant_id)
        if phone is None:
            return

        svc = NotificationService(session)
        await svc.send_message(
            tenant_id=tenant_id,
            event_id=event.event_id,
            recipient=phone,
            message_text=_MSG_ORDER_CREATED.format(order_id_short=_short_id(order_id)),
            order_id=order_id,
        )


async def handle_order_state_changed_notification(event: Event) -> None:
    """
    Send a state-specific message when order.state_changed fires.

    States handled: CONFIRMED, PAID, COMPLETED.
    Other states (INQUIRY, FAILED) are silently skipped.
    """
    payload = event.payload
    tenant_id: str = event.tenant_id
    order_id: str = payload.get("order_id", "")
    conversation_id: str = payload.get("conversation_id", "")
    new_state: str = payload.get("new_state", "")

    if not (tenant_id and order_id and conversation_id and new_state):
        logger.warning(
            "order.state_changed notification: missing fields event_id=%s — dropping",
            event.event_id,
        )
        return

    template = {
        OrderState.CONFIRMED: _MSG_ORDER_CONFIRMED,
        OrderState.PAID: _MSG_ORDER_PAID,
        OrderState.COMPLETED: _MSG_ORDER_COMPLETED,
    }.get(new_state)

    if template is None:
        # INQUIRY, FAILED — no notification needed
        return

    async with async_session_factory.begin() as session:
        phone = await _phone_from_conversation(session, conversation_id, tenant_id)
        if phone is None:
            return

        svc = NotificationService(session)
        await svc.send_message(
            tenant_id=tenant_id,
            event_id=event.event_id,
            recipient=phone,
            message_text=template.format(order_id_short=_short_id(order_id)),
            order_id=order_id,
        )


async def handle_payment_confirmed_notification(event: Event) -> None:
    """
    Send "Payment successful" when a payment.confirmed event arrives.

    payment.confirmed does not carry conversation_id, so we traverse
    order → conversation to find the customer's phone number.
    """
    payload = event.payload
    tenant_id: str = payload.get("tenant_id", "") or event.tenant_id
    order_id: str = payload.get("order_id", "")

    if not (tenant_id and order_id):
        logger.warning(
            "payment.confirmed notification: missing fields event_id=%s — dropping",
            event.event_id,
        )
        return

    async with async_session_factory.begin() as session:
        phone = await _phone_from_order(session, order_id, tenant_id)
        if phone is None:
            return

        svc = NotificationService(session)
        await svc.send_message(
            tenant_id=tenant_id,
            event_id=event.event_id,
            recipient=phone,
            message_text=_MSG_PAYMENT_CONFIRMED.format(
                order_id_short=_short_id(order_id)
            ),
            order_id=order_id,
        )


# ── Registration helpers ──────────────────────────────────────────────────────


def register_order_created_notification_handler(tenant_id: str) -> asyncio.Task:
    logger.info(
        "Registering order.created notification handler for tenant=%s", tenant_id
    )
    return create_listener_task(
        tenant_id=tenant_id,
        event_name=_EVT_ORDER_CREATED,
        handler=handle_order_created_notification,
    )


def register_order_state_changed_notification_handler(tenant_id: str) -> asyncio.Task:
    logger.info(
        "Registering order.state_changed notification handler for tenant=%s", tenant_id
    )
    return create_listener_task(
        tenant_id=tenant_id,
        event_name=_EVT_ORDER_STATE_CHANGED,
        handler=handle_order_state_changed_notification,
    )


def register_payment_confirmed_notification_handler(tenant_id: str) -> asyncio.Task:
    logger.info(
        "Registering payment.confirmed notification handler for tenant=%s", tenant_id
    )
    return create_listener_task(
        tenant_id=tenant_id,
        event_name=_EVT_PAYMENT_CONFIRMED,
        handler=handle_payment_confirmed_notification,
    )
