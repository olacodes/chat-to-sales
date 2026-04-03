"""
app/modules/payments/handlers.py

Listens for `payment.confirmed` events published by PaymentService after
a successful Paystack webhook and transitions the related order CONFIRMED → PAID.

Why a separate event handler instead of marking the order inside the webhook?
-----------------------------------------------------------------------------
The webhook endpoint is synchronous HTTP — it should acknowledge Paystack
quickly and return 200.  Delegating the order transition to an async
background task decouples the two operations:

  1. Webhook arrives  → PaymentService persists SUCCESS, emits payment.confirmed
  2. Background task  → OrderService transitions order to PAID

This also means the order transition inherits the same retry / error isolation
guarantees as every other event-driven step in the pipeline.

Wiring
------
Call register_payment_confirmed_handler(tenant_id) in app/main.py's lifespan:

    from app.modules.payments.handlers import register_payment_confirmed_handler

    _listener_tasks.append(register_payment_confirmed_handler("tenant-abc-123"))
"""

import asyncio

from app.core.logging import get_logger
from app.infra.database import async_session_factory
from app.infra.event_bus import Event, create_listener_task
from app.modules.orders.service import OrderService

logger = get_logger(__name__)

_PAYMENT_CONFIRMED_EVENT = "payment.confirmed"


async def handle_payment_confirmed(event: Event) -> None:
    """
    Transition an order CONFIRMED → PAID after a successful payment.

    Uses async_session_factory.begin() so the transaction auto-commits on
    success and auto-rolls back on error — consistent with how every other
    event handler in this codebase operates.

    OrderService.handle_payment_confirmed() does NOT call commit; begin()
    owns the transaction.
    """
    payload = event.payload
    order_id: str = payload.get("order_id", "")
    # tenant_id is embedded in the payload AND available as event.tenant_id
    tenant_id: str = payload.get("tenant_id", "") or event.tenant_id
    payment_id: str = payload.get("payment_id", "")
    reference: str = payload.get("reference", "")

    if not (order_id and tenant_id):
        logger.warning(
            "PaymentConfirmed handler: missing order_id or tenant_id "
            "event_id=%s — dropping",
            event.event_id,
        )
        return

    logger.info(
        "PaymentConfirmed: processing payment_id=%s order_id=%s reference=%s",
        payment_id,
        order_id,
        reference,
    )

    async with async_session_factory.begin() as session:
        svc = OrderService(session)
        order = await svc.handle_payment_confirmed(
            order_id=order_id, tenant_id=tenant_id
        )

    if order is None:
        logger.warning(
            "PaymentConfirmed: order transition skipped order_id=%s "
            "(not found or already in terminal state)",
            order_id,
        )
    else:
        logger.info(
            "PaymentConfirmed: order transitioned to PAID " "order_id=%s payment_id=%s",
            order.id,
            payment_id,
        )


def register_payment_confirmed_handler(tenant_id: str) -> asyncio.Task:
    """
    Start a background task that consumes `payment.confirmed` events for the
    given tenant and transitions affected orders to PAID state.

    Returns the task so the caller can cancel it on shutdown.
    """
    logger.info("Registering payment.confirmed handler for tenant=%s", tenant_id)
    return create_listener_task(
        tenant_id=tenant_id,
        event_name=_PAYMENT_CONFIRMED_EVENT,
        handler=handle_payment_confirmed,
    )
