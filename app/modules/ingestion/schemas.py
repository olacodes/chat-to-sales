import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


# ── Channel-agnostic inbound schema ──────────────────────────────────────────


class Channel(StrEnum):
    WHATSAPP = "whatsapp"
    SMS = "sms"
    WEB = "web"


# E.164 phone number: optional + then 7–15 digits
_PHONE_RE = re.compile(r"^\+?[1-9]\d{6,14}$")


class InboundMessageRequest(BaseModel):
    """
    Normalised inbound message accepted by POST /api/v1/webhooks/webhook.

    This is the canonical entry point for messages regardless of channel.
    The Meta Cloud API raw webhook is still accepted at POST /webhooks/whatsapp.
    """

    channel: Channel = Field(..., description="Source channel: whatsapp | sms | web")
    sender_identifier: str = Field(
        ...,
        description="Sender identifier — E.164 phone number or opaque web session ID",
        min_length=3,
        max_length=40,
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_sender(cls, data: dict) -> dict:
        """Accept 'sender' as a backward-compatible alias for 'sender_identifier'."""
        if (
            isinstance(data, dict)
            and "sender_identifier" not in data
            and "sender" in data
        ):
            data = {**data, "sender_identifier": data["sender"]}
        return data

    message: str = Field(
        ...,
        description="Raw message text from the sender",
        min_length=1,
        max_length=4096,
    )
    tenant_id: str = Field(
        ...,
        description="UUID of the owning tenant — injected by the gateway or read from X-Tenant-ID header",
        min_length=1,
    )
    message_id: str | None = Field(
        default=None,
        description="Channel-assigned message ID (e.g. WhatsApp wamid). Used for deduplication.",
    )
    # Set when the inbound message carries media (image, audio, video, document).
    # The message field will contain a sentinel like "[image]" or "[audio]".
    media_id: str | None = Field(
        default=None,
        description="Meta media object ID — present for image/audio/video messages.",
    )
    media_type: str | None = Field(
        default=None,
        description="MIME type of the media, e.g. 'image/jpeg' or 'audio/ogg'.",
    )
    sender_name: str | None = Field(
        default=None,
        description="WhatsApp profile name of the sender (from contacts array).",
    )

    @field_validator("sender_identifier")
    @classmethod
    def validate_sender(cls, v: str) -> str:
        v = v.strip()
        # Only enforce E.164 for phone-based channels at parse time.
        # Web sessions may use arbitrary IDs.
        return v

    @field_validator("message")
    @classmethod
    def strip_message(cls, v: str) -> str:
        return v.strip()

    @field_validator("channel", mode="before")
    @classmethod
    def normalise_channel(cls, v: str) -> str:
        return str(v).strip().lower()


class NormalizedMessage(BaseModel):
    """
    The cleaned, canonical form of an inbound message ready for downstream processing.
    Produced by IngestionService.normalize().
    """

    channel: Channel
    sender_identifier: str  # normalised (stripped)
    message: str  # stripped
    message_lower: str  # lowercase — useful for keyword matching
    word_count: int
    tenant_id: str
    is_empty: bool  # True only when message was whitespace-only before strip
    media_id: str | None = None
    media_type: str | None = None
    sender_name: str | None = None


class MessageReceivedPayload(BaseModel):
    """Payload embedded inside the MessageReceived event."""

    channel: str
    sender_identifier: str
    # customer_identifier mirrors sender_identifier; kept explicit so downstream
    # handlers never need to know which field holds the identity.
    customer_identifier: str
    message: str
    message_lower: str
    word_count: int
    tenant_id: str
    message_id: str | None = None  # channel-assigned ID forwarded for deduplication
    media_id: str | None = None
    media_type: str | None = None
    sender_name: str | None = None

    model_config = {"from_attributes": True}


# ── Meta Cloud API raw webhook types (kept for META push endpoint) ─────────────


class WhatsAppContact(BaseModel):
    profile: dict[str, Any]
    wa_id: str


class WhatsAppMessage(BaseModel):
    from_: str = Field(alias="from")
    id: str
    timestamp: str
    type: str
    text: dict[str, str] | None = None

    model_config = {"populate_by_name": True}


class WhatsAppValue(BaseModel):
    messaging_product: str
    metadata: dict[str, Any]
    contacts: list[WhatsAppContact] = []
    messages: list[WhatsAppMessage] = []


class WhatsAppChange(BaseModel):
    value: WhatsAppValue
    field: str


class WhatsAppEntry(BaseModel):
    id: str
    changes: list[WhatsAppChange]


class WhatsAppWebhookPayload(BaseModel):
    object: str
    entry: list[WhatsAppEntry]
