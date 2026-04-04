"""
Ingestion module — receives inbound WhatsApp webhooks from the Meta platform
and a channel-agnostic POST /webhook for internal/normalised message ingestion.

Responsibilities:
  - Verify webhook challenge (GET /webhooks/whatsapp)
  - Validate HMAC-SHA256 signature on Meta webhooks (POST /webhooks/whatsapp)
  - Accept normalised inbound messages (POST /webhooks/webhook)
  - Deserialise and validate payloads with Pydantic
  - Emit MessageReceived domain events for downstream processing
"""

import hashlib
import hmac
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status

from app.core.config import Settings, get_settings
from app.core.exceptions import InvalidWebhookSignatureError
from app.core.logging import get_logger
from app.infra.event_bus import Event, publish_event
from app.modules.ingestion.schemas import (
    InboundMessageRequest,
    NormalizedMessage,
    WhatsAppWebhookPayload,
)
from app.modules.ingestion.service import IngestionService

logger = get_logger(__name__)
router = APIRouter(prefix="/webhooks", tags=["Ingestion"])


# ── Channel-agnostic inbound message endpoint ─────────────────────────────────


@router.post(
    "/webhook",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive a normalised inbound message",
    description=(
        "Accepts a structured message from any supported channel, normalises it, "
        "and publishes a `message.received` event on the Redis event bus. "
        "Use this endpoint for internal integrations; the raw Meta webhook "
        "is at `POST /webhooks/whatsapp`."
    ),
)
async def receive_message(
    body: InboundMessageRequest,
) -> NormalizedMessage:
    svc = IngestionService()
    normalized = await svc.process(body)
    return normalized


# ── Webhook verification (WhatsApp challenge) ─────────────────────────────────


@router.get("/whatsapp", summary="WhatsApp webhook verification")
async def verify_whatsapp_webhook(
    hub_mode: Annotated[str, Query(alias="hub.mode")],
    hub_challenge: Annotated[str, Query(alias="hub.challenge")],
    hub_verify_token: Annotated[str, Query(alias="hub.verify_token")],
    settings: Annotated[Settings, Depends(get_settings)],
) -> int:
    if hub_mode != "subscribe" or hub_verify_token != settings.WHATSAPP_VERIFY_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Verification failed."
        )
    logger.info("WhatsApp webhook verified.")
    return int(hub_challenge)


# ── Inbound messages ──────────────────────────────────────────────────────────


@router.post(
    "/whatsapp", summary="Receive WhatsApp messages", status_code=status.HTTP_200_OK
)
async def receive_whatsapp_message(
    request: Request,
    payload: WhatsAppWebhookPayload,
    settings: Annotated[Settings, Depends(get_settings)],
    x_hub_signature_256: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    await _verify_signature(request, x_hub_signature_256, settings.WHATSAPP_APP_SECRET)

    # Extract the first message from the Meta payload and normalise it
    # into the same message.received event shape used by POST /webhook.
    sender_id = ""
    content = ""
    external_id = ""
    try:
        first_msg = payload.entry[0].changes[0].value.messages[0]
        sender_id = first_msg.from_
        content = (first_msg.text or {}).get("body", "")
        external_id = first_msg.id
    except (IndexError, AttributeError):
        pass  # status/delivery notification — nothing to persist

    if sender_id and content:
        tenant_id = settings.WHATSAPP_PHONE_NUMBER_ID or "default"
        event = Event(
            event_name="message.received",
            tenant_id=tenant_id,
            payload={
                "channel": "whatsapp",
                "sender_identifier": sender_id,
                "message": content,
                "message_id": external_id,
            },
        )
        await publish_event(event)
        logger.info(
            "WhatsApp message forwarded to event bus — event_id=%s", event.event_id
        )

    return {"status": "accepted"}


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _verify_signature(
    request: Request, signature_header: str | None, app_secret: str
) -> None:
    """Reject requests with an invalid HMAC-SHA256 signature."""
    if not app_secret:
        return  # Signature checking disabled when no secret is configured

    if not signature_header or not signature_header.startswith("sha256="):
        raise InvalidWebhookSignatureError()

    body = await request.body()
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    provided = signature_header.removeprefix("sha256=")

    if not hmac.compare_digest(expected, provided):
        raise InvalidWebhookSignatureError()
