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

from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import and_, select, update

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
    _scheduler.start()
    logger.info("Scheduler started — checking scheduled messages every 60 s")


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler. Call during app lifespan teardown."""
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
