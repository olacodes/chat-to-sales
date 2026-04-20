"""
app/modules/notifications/service.py

NotificationService — two entry points:

1. HTTP path (send)
   Accepts a NotificationPayload from the REST API (POST /notifications/send).
   Used for manual/admin triggered messages. No DB persistence, no idempotency.

2. Event-driven path (send_message)
   Called by event handlers in handlers.py.
   Persists a Notification row (event_id as idempotency key), dispatches the
   message to the customer via Meta Cloud API, then marks the row SENT or FAILED.

WhatsApp delivery
-----------------
Credentials (phone_number_id + access_token) are looked up from tenant_channels
at dispatch time so that:
  - Rotating a token via /channels/whatsapp/connect takes effect immediately.
  - The same code path works for every tenant without any static config.

Meta Cloud API call:
    POST https://graph.facebook.com/v25.0/{phone_number_id}/messages
    Authorization: Bearer {access_token}
    Body: {
        "messaging_product": "whatsapp",
        "to": "{recipient}",
        "type": "text",
        "text": {"body": "{message_text}"}
    }
"""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.infra.crypto import decrypt_token
from app.modules.channels.repository import ChannelRepository
from app.modules.notifications.models import NotificationStatus
from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.schemas import NotificationChannel, NotificationPayload

logger = get_logger(__name__)

_META_API_BASE = "https://graph.facebook.com/v25.0"
_WHATSAPP_TIMEOUT = 10.0


class NotificationService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._repo = NotificationRepository(db)
        self._channel_repo = ChannelRepository(db)

    # ── HTTP-driven path ──────────────────────────────────────────────────────

    async def send(self, payload: NotificationPayload) -> None:
        """
        Dispatch a notification from a REST API request.
        No DB record, no idempotency — used for admin/manual triggers.
        """
        match payload.channel:
            case NotificationChannel.WHATSAPP:
                await self._dispatch_whatsapp(
                    tenant_id=payload.tenant_id,
                    recipient=payload.recipient,
                    message_text=payload.template_name,
                )
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
        the call is a no-op — the same event can never produce a second send.

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
                await self._dispatch_whatsapp(
                    tenant_id=tenant_id,
                    recipient=recipient,
                    message_text=message_text,
                )
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

    async def _dispatch_whatsapp(
        self,
        tenant_id: str,
        recipient: str,
        message_text: str,
    ) -> None:
        """
        Send a message to a WhatsApp number via the Meta Cloud API.

        Credentials are fetched from tenant_channels so token rotations
        (via /channels/whatsapp/connect) take effect without a restart.

        Raises httpx.HTTPStatusError on a non-2xx response from Meta so
        the caller can mark the notification FAILED.
        """
        channel_record = await self._channel_repo.get_by_tenant_and_channel(
            tenant_id=tenant_id,
            channel="whatsapp",
        )
        if channel_record is None:
            raise ValueError(
                f"No WhatsApp channel configured for tenant={tenant_id}. "
                "Connect a channel via POST /api/v1/channels/whatsapp/connect first."
            )

        phone_number_id = channel_record.phone_number_id
        access_token = decrypt_token(channel_record.encrypted_access_token)

        url = f"{_META_API_BASE}/{phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        body = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {"body": message_text},
        }

        async with httpx.AsyncClient(timeout=_WHATSAPP_TIMEOUT) as client:
            response = await client.post(url, headers=headers, json=body)

        if response.is_success:
            logger.info(
                "WhatsApp sent → %s via phone_number_id=%s", recipient, phone_number_id
            )
        else:
            logger.error(
                "WhatsApp API error status=%s body=%s recipient=%s",
                response.status_code,
                response.text,
                recipient,
            )
            response.raise_for_status()
