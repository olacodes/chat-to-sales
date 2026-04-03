"""
app/modules/notifications/service.py

NotificationService — two entry points:

1. HTTP path (send)
   Accepts a NotificationPayload from the REST API (POST /notifications/send).
   Used for manual/admin triggered messages. No DB persistence, no idempotency.

2. Event-driven path (send_message)
   Called by event handlers in handlers.py.
   Persists a Notification row (event_id as idempotency key), logs the mock
   send, then marks the row SENT or FAILED.

Upgrading to real WhatsApp delivery
------------------------------------
Replace `_dispatch_whatsapp()` with an HTTP call to the Meta Cloud API:

    POST https://graph.facebook.com/v18.0/{phone_number_id}/messages
    Authorization: Bearer {WHATSAPP_TOKEN}
    Body: { "messaging_product": "whatsapp", "to": recipient,
            "type": "text", "text": {"body": message_text} }

The rest of the service (idempotency, DB persistence, status update) stays
unchanged.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.notifications.models import NotificationStatus
from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.schemas import NotificationChannel, NotificationPayload

logger = get_logger(__name__)


class NotificationService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._repo = NotificationRepository(db)

    # ── HTTP-driven path ──────────────────────────────────────────────────────

    async def send(self, payload: NotificationPayload) -> None:
        """
        Dispatch a notification from a REST API request.
        No DB record, no idempotency — used for admin/manual triggers.
        """
        match payload.channel:
            case NotificationChannel.WHATSAPP:
                await self._dispatch_whatsapp(payload.recipient, payload.template_name)
            case NotificationChannel.SMS:
                logger.info("SMS → %s", payload.recipient)
            case NotificationChannel.EMAIL:
                logger.info("Email → %s", payload.recipient)
            case _:
                logger.warning("Unknown notification channel: %s", payload.channel)

    # ── Event-driven path ─────────────────────────────────────────────────────

    async def send_message(
        self,
        *,
        tenant_id: str,
        event_id: str,
        recipient: str,
        message_text: str,
        channel: str = "whatsapp",
        order_id: str | None = None,
    ) -> None:
        """
        Persist + dispatch a notification triggered by a system event.

        Idempotency: if a notification row with this event_id already exists
        the call is a no-op - the same event can never produce a second send.

        The caller must own the transaction (async_session_factory.begin()).
        This method does NOT commit.
        """
        existing = await self._repo.get_by_event_id(event_id)
        if existing is not None:
            logger.info(
                "Notification already sent for event_id=%s — skipping", event_id
            )
            return

        notification = await self._repo.create(
            tenant_id=tenant_id,
            event_id=event_id,
            recipient=recipient,
            message_text=message_text,
            channel=channel,
            order_id=order_id,
        )

        try:
            if channel == "whatsapp":
                await self._dispatch_whatsapp(recipient, message_text)
            else:
                logger.info("MOCK SEND [%s] → %s: %s", channel, recipient, message_text)

            await self._repo.update_status(notification, NotificationStatus.SENT)
            logger.info(
                "Notification sent id=%s recipient=%s event_id=%s",
                notification.id,
                recipient,
                event_id,
            )
        except Exception as exc:
            await self._repo.update_status(notification, NotificationStatus.FAILED)
            logger.error(
                "Notification failed id=%s recipient=%s event_id=%s: %s",
                notification.id,
                recipient,
                event_id,
                exc,
            )
            raise

    # ── Dispatch adapters ─────────────────────────────────────────────────────

    async def _dispatch_whatsapp(self, recipient: str, message_text: str) -> None:
        """
        MVP: log the message. Replace this body with the Meta Cloud API call
        to go live. No other code needs to change.
        """
        logger.info(
            "WHATSAPP → %s | %s",
            recipient,
            message_text,
        )
