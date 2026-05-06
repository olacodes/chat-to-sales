"""
app/infra/scheduler.py

APScheduler-based background job that fires pending scheduled messages.

Design notes
------------
- Uses AsyncIOScheduler so it runs inside the existing asyncio event loop.
- Fires every 60 seconds; queries for pending messages due now or in the past.
- Calls ConversationService.add_message() so the existing reply pipeline
  (Redis pub/sub, WebSocket push, etc.) is triggered automatically.
- Uses the same async_session_factory as the rest of the app.
"""

from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import and_, select, update

from app.core.config import get_settings
from app.core.logging import get_logger
from app.infra.database import async_session_factory
from app.modules.conversation.models import ScheduledMessage
from app.modules.conversation.service import ConversationService

logger = get_logger(__name__)

_scheduler = AsyncIOScheduler(timezone="UTC")


async def _fire_due_messages() -> None:
    """Query all pending scheduled messages that are due and send them."""
    now = datetime.now(tz=timezone.utc)

    async with async_session_factory() as session:
        result = await session.execute(
            select(ScheduledMessage).where(
                and_(
                    ScheduledMessage.status == "pending",
                    ScheduledMessage.scheduled_for <= now,
                )
            )
        )
        due: list[ScheduledMessage] = list(result.scalars().all())

    if not due:
        return

    logger.info("Scheduler: firing %d scheduled message(s)", len(due))

    for sm in due:
        async with async_session_factory() as session:
            try:
                svc = ConversationService(session)
                await svc.add_message(
                    conversation_id=sm.conversation_id,
                    tenant_id=sm.tenant_id,
                    content=sm.content,
                    sender_role="assistant",
                    external_id=None,
                )
                await session.execute(
                    update(ScheduledMessage)
                    .where(ScheduledMessage.id == sm.id)
                    .values(status="sent")
                )
                await session.commit()
                logger.info("Scheduler: sent scheduled message %s", sm.id)
            except Exception:  # noqa: BLE001
                logger.exception("Scheduler: failed to send scheduled message %s", sm.id)


_REMINDER_DELAY_HOURS = 0.01  # TODO: revert to 2 after testing
_REMINDER_INTERVAL_MINUTES = 1  # TODO: revert to 30 after testing


async def _send_order_reminders() -> None:
    """Find stale INQUIRY orders and send a single reminder to the trader."""
    from app.modules.notifications.service import NotificationService
    from app.modules.orders.models import Order, OrderState
    import app.modules.orders.whatsapp as wa

    now = datetime.now(tz=timezone.utc)
    cutoff = now - timedelta(hours=_REMINDER_DELAY_HOURS)
    settings = get_settings()
    platform_tenant_id = settings.TENANT_ID

    # Find orders: INQUIRY, older than 2h, no reminder sent yet, has trader_phone
    async with async_session_factory() as session:
        result = await session.execute(
            select(Order).where(
                and_(
                    Order.state == OrderState.INQUIRY,
                    Order.created_at <= cutoff,
                    Order.reminder_sent_at.is_(None),
                    Order.trader_phone.is_not(None),
                )
            )
        )
        stale_orders: list[Order] = list(result.scalars().all())

    if not stale_orders:
        return

    logger.info("Order reminders: found %d stale INQUIRY orders", len(stale_orders))

    for order in stale_orders:
        order_ref = order.id[:8]
        hours_ago = max(1, int((now - order.created_at).total_seconds() / 3600))
        total = int(order.amount or 0)
        customer_phone = order.customer_phone or "unknown"
        trader_phone = order.trader_phone

        text = wa.order_reminder_to_trader(
            customer_phone=customer_phone,
            total=total,
            order_ref=order_ref,
            hours_ago=hours_ago,
        )

        try:
            async with async_session_factory.begin() as session:
                svc = NotificationService(session)
                await svc.send_message(
                    tenant_id=platform_tenant_id,
                    event_id=f"order.reminder.{order.id}",
                    recipient=trader_phone,
                    message_text=text,
                    channel="whatsapp",
                    channel_tenant_id=platform_tenant_id,
                )

            # Mark as reminded (separate session to avoid coupling with notification tx)
            async with async_session_factory.begin() as session:
                await session.execute(
                    update(Order)
                    .where(Order.id == order.id)
                    .values(reminder_sent_at=now)
                )

            logger.info(
                "Order reminder sent: order_id=%s trader=%s ref=%s",
                order.id, trader_phone, order_ref,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Order reminder failed: order_id=%s trader=%s", order.id, trader_phone
            )


def start_scheduler() -> None:
    """Add jobs and start the scheduler. Call once during app lifespan startup."""
    _scheduler.add_job(
        _fire_due_messages,
        trigger="interval",
        seconds=60,
        id="fire_scheduled_messages",
        replace_existing=True,
        misfire_grace_time=30,
    )
    _scheduler.add_job(
        _send_order_reminders,
        trigger="interval",
        minutes=_REMINDER_INTERVAL_MINUTES,
        id="send_order_reminders",
        replace_existing=True,
        misfire_grace_time=60,
    )
    _scheduler.start()
    logger.info(
        "Scheduler started — messages every 60s, order reminders every %dm",
        _REMINDER_INTERVAL_MINUTES,
    )


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler. Call during app lifespan teardown."""
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
