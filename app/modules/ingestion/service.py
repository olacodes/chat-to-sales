"""
app/modules/ingestion/service.py

IngestionService — normalises an inbound message and publishes
a MessageReceived event on the Redis event bus.

Keeping event publishing out of the router keeps the router thin
and makes the service independently testable without HTTP machinery.
"""

from app.core.logging import get_logger
from app.infra.event_bus import Event, publish_event
from app.modules.ingestion.schemas import (
    InboundMessageRequest,
    MessageReceivedPayload,
    NormalizedMessage,
)

logger = get_logger(__name__)

# Canonical event name consumed by conversation, orders, and notification modules
MESSAGE_RECEIVED_EVENT = "message.received"


class IngestionService:
    # ── Normalisation ─────────────────────────────────────────────────────────

    @staticmethod
    def normalize(request: InboundMessageRequest) -> NormalizedMessage:
        """
        Produce a NormalizedMessage from a raw InboundMessageRequest.

        Normalisation rules:
        - message is stripped of leading/trailing whitespace (already done by validator)
        - message_lower is the lowercased form, useful for keyword matching downstream
        - word_count is computed from whitespace-split tokens
        - sender is kept as-is (phone numbers are already E.164-ish from the validator)
        """
        stripped = request.message.strip()
        words = stripped.split()

        return NormalizedMessage(
            channel=request.channel,
            sender=request.sender.strip(),
            message=stripped,
            message_lower=stripped.lower(),
            word_count=len(words),
            tenant_id=request.tenant_id,
            is_empty=len(stripped) == 0,
        )

    # ── Event publishing ──────────────────────────────────────────────────────

    async def process(self, request: InboundMessageRequest) -> NormalizedMessage:
        """
        Normalize the message then publish a MessageReceived event.

        Returns the NormalizedMessage so the router can include it in the response.
        """
        normalized = self.normalize(request)

        event_payload = MessageReceivedPayload(
            channel=normalized.channel,
            sender=normalized.sender,
            message=normalized.message,
            message_lower=normalized.message_lower,
            word_count=normalized.word_count,
            tenant_id=normalized.tenant_id,
            message_id=request.message_id,
        )

        event = Event(
            event_name=MESSAGE_RECEIVED_EVENT,
            tenant_id=normalized.tenant_id,
            payload=event_payload.model_dump(),
        )

        receivers = await publish_event(event)
        logger.info(
            "MessageReceived published | tenant=%s sender=%s channel=%s "
            "words=%d event_id=%s receivers=%d",
            normalized.tenant_id,
            normalized.sender,
            normalized.channel,
            normalized.word_count,
            event.event_id,
            receivers,
        )

        return normalized
