"""
app/modules/notifications/repository.py

Data-access layer for Notification entities.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.notifications.models import Notification, NotificationStatus

logger = get_logger(__name__)


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_event_id(self, event_id: str) -> Notification | None:
        """
        Return a Notification whose event_id matches, or None.
        Used by the service to enforce send-once idempotency.
        """
        result = await self._session.execute(
            select(Notification).where(Notification.event_id == event_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        tenant_id: str,
        event_id: str,
        recipient: str,
        message_text: str,
        channel: str = "whatsapp",
        order_id: str | None = None,
    ) -> Notification:
        """Persist a new PENDING notification and flush to get its PK."""
        notification = Notification(
            tenant_id=tenant_id,
            event_id=event_id,
            recipient=recipient,
            message_text=message_text,
            channel=channel,
            status=NotificationStatus.PENDING,
            order_id=order_id,
        )
        self._session.add(notification)
        await self._session.flush()
        logger.debug(
            "Notification created id=%s event_id=%s recipient=%s",
            notification.id,
            event_id,
            recipient,
        )
        return notification

    async def update_status(
        self,
        notification: Notification,
        status: NotificationStatus,
    ) -> Notification:
        """Update delivery status and flush."""
        notification.status = status
        self._session.add(notification)
        await self._session.flush()
        return notification
