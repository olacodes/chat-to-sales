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


_REMINDER_DELAY_HOURS = 1
_REMINDER_INTERVAL_MINUTES = 30

# WAT (West Africa Time) = UTC+1. Only send reminders 8am–8pm.
_WAT_OFFSET_HOURS = 1
_BUSINESS_HOUR_START = 8
_BUSINESS_HOUR_END = 20


def _is_business_hours(now: datetime) -> bool:
    """Return True if the current time is within business hours in WAT."""
    wat_hour = (now.hour + _WAT_OFFSET_HOURS) % 24
    return _BUSINESS_HOUR_START <= wat_hour < _BUSINESS_HOUR_END


async def _send_order_reminders() -> None:
    """Find stale INQUIRY orders and send a single reminder to the trader."""
    from app.modules.notifications.service import NotificationService
    from app.modules.orders.models import Order, OrderState
    import app.modules.orders.whatsapp as wa

    now = datetime.now(tz=timezone.utc)
    if not _is_business_hours(now):
        return

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

        body_text, buttons = wa.order_reminder_to_trader(
            customer_phone=customer_phone,
            total=total,
            order_ref=order_ref,
            hours_ago=hours_ago,
        )

        try:
            async with async_session_factory.begin() as session:
                svc = NotificationService(session)
                await svc.send_interactive(
                    tenant_id=platform_tenant_id,
                    event_id=f"order.reminder.{order.id}",
                    recipient=trader_phone,
                    body_text=body_text,
                    buttons=buttons,
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


_DEBT_REMINDER_INTERVAL_HOURS = 6


async def _send_debt_reminders() -> None:
    """
    Find active credit sales due for a reminder and send them.

    Two paths:
    - Order-linked debts (conversation_id set): send reminder to customer
      through the conversation (existing CreditSaleService.send_reminder).
    - Standalone debts (no conversation_id): send reminder to the TRADER
      to follow up manually.
    """
    from app.modules.credit_sales.models import CreditSale, CreditSaleStatus
    from app.modules.credit_sales.service import CreditSaleService
    from app.modules.notifications.service import NotificationService
    from app.modules.orders.session import get_trader_by_tenant_cache
    from app.modules.onboarding.repository import TraderRepository
    import app.modules.orders.whatsapp as wa

    now = datetime.now(tz=timezone.utc)
    if not _is_business_hours(now):
        return
    settings = get_settings()
    platform_tenant_id = settings.TENANT_ID

    # Find all active credit sales that are due for a reminder
    async with async_session_factory() as session:
        result = await session.execute(
            select(CreditSale).where(
                and_(
                    CreditSale.status == CreditSaleStatus.ACTIVE,
                    CreditSale.reminders_sent < CreditSale.max_reminders,
                )
            )
        )
        all_active: list[CreditSale] = list(result.scalars().all())

    if not all_active:
        return

    # Filter to those that are due (interval has passed)
    due: list[CreditSale] = []
    for cs in all_active:
        last = cs.last_reminded_at or cs.created_at
        if last and (now - last).total_seconds() >= cs.reminder_interval_days * 86400:
            due.append(cs)

    if not due:
        return

    logger.info("Debt reminders: found %d credit sales due for reminder", len(due))

    for cs in due:
        try:
            if cs.conversation_id:
                # Order-linked: send reminder to customer via conversation
                async with async_session_factory.begin() as session:
                    svc = CreditSaleService(session)
                    await svc.send_reminder(cs.id, tenant_id=cs.tenant_id)

                # Notify the trader that we sent the reminder
                trader_data = await get_trader_by_tenant_cache(cs.tenant_id)
                if not trader_data:
                    async with async_session_factory() as session:
                        repo = TraderRepository(session)
                        trader = await repo.get_by_tenant(cs.tenant_id)
                    trader_phone = trader.phone_number if trader else ""
                else:
                    trader_phone = trader_data.get("phone_number", "")

                if trader_phone:
                    async with async_session_factory.begin() as session:
                        notify_svc = NotificationService(session)
                        await notify_svc.send_message(
                            tenant_id=platform_tenant_id,
                            event_id=f"debt.reminder_notify.{cs.id}.{cs.reminders_sent}",
                            recipient=trader_phone,
                            message_text=wa.debt_customer_reminded_notification(
                                cs.customer_name, int(cs.amount), cs.reminders_sent,
                            ),
                            channel="whatsapp",
                            channel_tenant_id=platform_tenant_id,
                        )

                logger.info(
                    "Debt reminder sent to customer + trader notified: credit_sale=%s customer=%s",
                    cs.id, cs.customer_name,
                )
            else:
                # Standalone: remind the trader to follow up
                # Find trader phone by tenant
                trader_data = await get_trader_by_tenant_cache(cs.tenant_id)
                if not trader_data:
                    async with async_session_factory() as session:
                        repo = TraderRepository(session)
                        trader = await repo.get_by_tenant(cs.tenant_id)
                    if not trader:
                        continue
                    trader_phone = trader.phone_number
                else:
                    trader_phone = trader_data.get("phone_number", "")

                if not trader_phone:
                    continue

                days_ago = max(1, int((now - cs.created_at).total_seconds() / 86400))
                text = wa.debt_reminder_to_trader(
                    customer_name=cs.customer_name,
                    amount=int(cs.amount),
                    days_ago=days_ago,
                )

                async with async_session_factory.begin() as session:
                    svc = NotificationService(session)
                    await svc.send_message(
                        tenant_id=platform_tenant_id,
                        event_id=f"debt.reminder.{cs.id}.{cs.reminders_sent}",
                        recipient=trader_phone,
                        message_text=text,
                        channel="whatsapp",
                        channel_tenant_id=platform_tenant_id,
                    )

                # Increment reminder count
                async with async_session_factory.begin() as session:
                    await session.execute(
                        update(CreditSale)
                        .where(CreditSale.id == cs.id)
                        .values(
                            reminders_sent=cs.reminders_sent + 1,
                            last_reminded_at=now,
                        )
                    )

                logger.info(
                    "Debt reminder sent to trader: credit_sale=%s trader=%s customer=%s",
                    cs.id, trader_phone, cs.customer_name,
                )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Debt reminder failed: credit_sale=%s customer=%s",
                cs.id, cs.customer_name,
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
    _scheduler.add_job(
        _send_debt_reminders,
        trigger="interval",
        hours=_DEBT_REMINDER_INTERVAL_HOURS,
        id="send_debt_reminders",
        replace_existing=True,
        misfire_grace_time=120,
    )
    _scheduler.start()
    logger.info(
        "Scheduler started — messages every 60s, order reminders every %dm, debt reminders every %dh",
        _REMINDER_INTERVAL_MINUTES,
        _DEBT_REMINDER_INTERVAL_HOURS,
    )


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler. Call during app lifespan teardown."""
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
