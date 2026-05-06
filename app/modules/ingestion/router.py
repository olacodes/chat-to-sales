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
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status

from app.core.config import Settings, get_settings
from app.core.exceptions import InvalidWebhookSignatureError
from app.core.logging import get_logger
from app.modules.ingestion.schemas import (
    InboundMessageRequest,
    NormalizedMessage,
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
    return await svc.process(body)


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
    settings: Annotated[Settings, Depends(get_settings)],
    x_hub_signature_256: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    body = await request.body()
    _verify_signature_bytes(body, x_hub_signature_256, settings.WHATSAPP_APP_SECRET)

    # Parse the raw body directly — avoids a second read via request.json()
    # and never triggers a 422 regardless of Meta's payload shape.
    try:
        raw: dict[str, Any] = json.loads(body)
    except Exception:
        logger.warning("WhatsApp webhook — could not parse JSON body")
        return {"status": "accepted"}

    # v25.0 Cloud API path: object → entry[].changes[].value.messages[]
    # Status/delivery webhooks have a `statuses` array instead of `messages`;
    # they are silently ignored here.
    sender_id = ""
    sender_name: str | None = None
    content = ""
    external_id = ""
    media_id: str | None = None
    media_type: str | None = None

    # Meta Cloud API MIME types for WhatsApp audio messages
    _AUDIO_MIME_TYPES: dict[str, str] = {
        "audio/ogg": "audio/ogg",
        "audio/mpeg": "audio/mpeg",
        "audio/mp4": "audio/mp4",
        "audio/aac": "audio/aac",
        "audio/amr": "audio/amr",
    }

    try:
        value = raw["entry"][0]["changes"][0]["value"]
        first_msg = value["messages"][0]
        msg_type = first_msg.get("type", "")
        sender_id = first_msg.get("from", "")
        external_id = first_msg.get("id", "")

        # Extract WhatsApp profile name from contacts array
        contacts = value.get("contacts") or []
        if contacts:
            profile = contacts[0].get("profile") or {}
            sender_name = profile.get("name") or None

        if msg_type == "text":
            content = (first_msg.get("text") or {}).get("body", "")
        elif msg_type == "image":
            img = first_msg.get("image") or {}
            media_id = img.get("id", "")
            media_type = img.get("mime_type", "image/jpeg")
            content = "[image]"
            logger.debug("WhatsApp image received media_id=%s sender=%s", media_id, sender_id)
        elif msg_type == "audio":
            aud = first_msg.get("audio") or {}
            media_id = aud.get("id", "")
            media_type = aud.get("mime_type", "audio/ogg")
            content = "[audio]"
            logger.debug("WhatsApp audio received media_id=%s sender=%s", media_id, sender_id)
        elif msg_type == "interactive":
            interactive = first_msg.get("interactive") or {}
            reply_type = interactive.get("type", "")
            if reply_type == "button_reply":
                button = interactive.get("button_reply") or {}
                # Use the button ID as content — it contains the full command
                # (e.g. "CONFIRM 4ae8109e" or "YES") set when the button was sent.
                content = button.get("id", "") or button.get("title", "")
                logger.debug(
                    "WhatsApp button reply id=%s title=%s sender=%s",
                    button.get("id"),
                    button.get("title"),
                    sender_id,
                )
            elif reply_type == "list_reply":
                list_item = interactive.get("list_reply") or {}
                content = list_item.get("id", "") or list_item.get("title", "")
            else:
                logger.debug("WhatsApp interactive type=%s — ignoring", reply_type)
        else:
            # reaction, sticker, document, video — not handled yet
            logger.debug(
                "WhatsApp webhook — ignoring message type=%s", msg_type
            )
    except (KeyError, IndexError, TypeError):
        pass  # status/delivery notification — nothing to process

    if sender_id and content:
        tenant_id = settings.TENANT_ID
        inbound = InboundMessageRequest(
            channel="whatsapp",
            sender_identifier=sender_id,
            message=content,
            tenant_id=tenant_id,
            message_id=external_id or None,
            media_id=media_id or None,
            media_type=media_type or None,
            sender_name=sender_name,
        )
        svc = IngestionService()
        await svc.process(inbound)
        logger.info("WhatsApp message processed — sender=%s type=%s", sender_id, msg_type)

    return {"status": "accepted"}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _verify_signature_bytes(
    body: bytes, signature_header: str | None, app_secret: str
) -> None:
    """Reject requests with an invalid HMAC-SHA256 signature."""
    if not app_secret:
        return  # Signature checking disabled when no secret is configured

    if not signature_header or not signature_header.startswith("sha256="):
        logger.warning(
            "WhatsApp webhook — missing or malformed X-Hub-Signature-256 header "
            "(got: %r). Check that WHATSAPP_APP_SECRET is set and Meta has the "
            "correct webhook URL.",
            signature_header,
        )
        raise InvalidWebhookSignatureError()

    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    provided = signature_header.removeprefix("sha256=")

    if not hmac.compare_digest(expected, provided):
        logger.warning(
            "WhatsApp webhook — HMAC-SHA256 digest mismatch. "
            "Verify that WHATSAPP_APP_SECRET in your .env matches the "
            "'App Secret' on the Meta App Dashboard (not the Access Token)."
        )
        raise InvalidWebhookSignatureError()
