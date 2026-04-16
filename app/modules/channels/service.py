"""
app/modules/channels/service.py

WhatsAppChannelService — orchestrates the WhatsApp connect flow:

  1. Encrypt the access token
  2. Upsert the TenantChannel record (idempotent)
  3. Register the webhook with Meta (graceful failure)
  4. Emit a ChannelConnected event on the Redis bus
"""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.infra.crypto import encrypt_token
from app.infra.event_bus import Event, publish_event
from app.modules.channels.models import ChannelName
from app.modules.channels.repository import ChannelRepository
from app.modules.channels.schemas import WhatsAppConnectRequest, WhatsAppConnectResponse

logger = get_logger(__name__)

# Meta Graph API base — webhook subscription endpoint
_META_API_BASE = "https://graph.facebook.com/v25.0"
# How long (seconds) to wait for Meta's API before giving up
_WEBHOOK_TIMEOUT = 10.0
# Number of registration attempts before logging failure
_WEBHOOK_MAX_RETRIES = 2


class WhatsAppChannelService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = ChannelRepository(session)
        self._settings = get_settings()

    # ── Public entry point ────────────────────────────────────────────────────

    async def connect(self, req: WhatsAppConnectRequest) -> WhatsAppConnectResponse:
        """
        Connect (or reconnect) a tenant's WhatsApp Business account.

        Idempotent: repeated calls with the same tenant/channel simply
        update the stored token and re-attempt webhook registration.
        """
        # Step 1 — Encrypt the token before it ever touches the database.
        encrypted = encrypt_token(req.access_token)

        # Step 2 — Attempt webhook registration BEFORE the DB write so that a
        # Meta API rejection surfaces cleanly. Failures are non-fatal; the
        # channel is still stored so an operator can retry later.
        webhook_ok = await self._register_webhook(
            phone_number_id=req.phone_number_id,
            access_token=req.access_token,
        )

        # Step 3 — Upsert the channel record.
        _, created = await self._repo.upsert(
            tenant_id=req.tenant_id,
            channel=ChannelName.WHATSAPP,
            phone_number_id=req.phone_number_id,
            encrypted_access_token=encrypted,
            webhook_registered=webhook_ok,
        )

        action = "connected" if created else "reconnected"
        logger.info(
            "WhatsApp channel %s — tenant=%s phone_number_id=%s webhook=%s",
            action,
            req.tenant_id,
            req.phone_number_id,
            webhook_ok,
        )

        # Step 4 — Emit a ChannelConnected event for downstream listeners.
        await self._emit_connected_event(
            tenant_id=req.tenant_id,
            channel=ChannelName.WHATSAPP,
        )

        return WhatsAppConnectResponse(
            status="connected",
            channel=ChannelName.WHATSAPP,
            phone_number_id=req.phone_number_id,
            webhook_registered=webhook_ok,
        )

    # ── Webhook registration ──────────────────────────────────────────────────

    async def _register_webhook(
        self,
        *,
        phone_number_id: str,
        access_token: str,
    ) -> bool:
        """
        Subscribe the app to the WhatsApp webhook for this phone number.

        Uses the Meta Graph API v25.0 subscribed_apps endpoint.

        Failures are logged and swallowed — a webhook registration failure
        must NOT roll back the channel record. Operators can fix Meta config
        and the next connect call will retry.

        Returns True if Meta confirmed the subscription, False otherwise.
        """
        url = f"{_META_API_BASE}/{phone_number_id}/subscribed_apps"
        webhook_url = f"{self._settings.APP_BASE_URL}/api/v1/webhooks/whatsapp"

        for attempt in range(1, _WEBHOOK_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=_WEBHOOK_TIMEOUT) as client:
                    response = await client.post(
                        url,
                        headers={"Authorization": f"Bearer {access_token}"},
                        # The subscribed_apps endpoint uses query params, not JSON body.
                        params={"subscribed_fields": "messages"},
                    )

                if response.status_code == 200 and response.json().get("success"):
                    logger.info(
                        "Webhook registered with Meta — phone_number_id=%s url=%s",
                        phone_number_id,
                        webhook_url,
                    )
                    return True

                logger.warning(
                    "Meta webhook registration attempt %d/%d failed — "
                    "phone_number_id=%s status=%d body=%s",
                    attempt,
                    _WEBHOOK_MAX_RETRIES,
                    phone_number_id,
                    response.status_code,
                    response.text[:200],
                )

            except httpx.RequestError as exc:
                logger.warning(
                    "Meta webhook registration attempt %d/%d — network error: %s",
                    attempt,
                    _WEBHOOK_MAX_RETRIES,
                    exc,
                )

        logger.error(
            "Webhook registration failed after %d attempts — "
            "phone_number_id=%s. "
            "The channel record is stored; re-call connect to retry.",
            _WEBHOOK_MAX_RETRIES,
            phone_number_id,
        )
        return False

    # ── Event emission ────────────────────────────────────────────────────────

    async def _emit_connected_event(self, *, tenant_id: str, channel: str) -> None:
        """Publish a ChannelConnected event to the Redis event bus."""
        event = Event(
            event_name="channel.connected",
            tenant_id=tenant_id,
            payload={"channel": channel, "tenant_id": tenant_id},
        )
        try:
            await publish_event(event)
            logger.debug(
                "ChannelConnected event published — tenant=%s channel=%s event_id=%s",
                tenant_id,
                channel,
                event.event_id,
            )
        except Exception as exc:
            # Event bus failure must not abort the connect flow.
            logger.warning(
                "Failed to publish ChannelConnected event — tenant=%s error=%s",
                tenant_id,
                exc,
            )
