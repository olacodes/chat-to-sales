"""
app/modules/onboarding/handlers.py

Event-driven handler for the `conversation.message_saved` event.

Only WhatsApp messages are routed to the onboarding flow — other channels
(future SMS, web chat, etc.) are silently ignored.

Wiring
------
Call register_onboarding_handler() in app/main.py's lifespan:

    from app.modules.onboarding.handlers import register_onboarding_handler

    @asynccontextmanager
    async def lifespan(app):
        ...
        _listener_tasks.append(register_onboarding_handler())
        yield
"""

import asyncio

from app.core.logging import get_logger
from app.infra.database import async_session_factory
from app.infra.event_bus import Event, create_global_listener_task
from app.modules.onboarding.repository import TraderRepository
from app.modules.onboarding.service import OnboardingService

logger = get_logger(__name__)

_CONVERSATION_MESSAGE_SAVED_EVENT = "conversation.message_saved"


async def handle_onboarding(event: Event) -> None:
    """
    Route an inbound WhatsApp message through the onboarding state machine.

    Skips non-WhatsApp channels and events with missing required fields.
    All state transitions and DB writes are owned by OnboardingService.
    """
    payload = event.payload
    tenant_id: str = event.tenant_id
    channel: str = payload.get("channel", "")

    if channel != "whatsapp":
        return

    phone_number: str = payload.get("sender_identifier") or payload.get("customer_identifier", "")
    content: str = payload.get("content", "")
    message_id: str = payload.get("id", "")
    media_id: str | None = payload.get("media_id")
    media_type: str | None = payload.get("media_type")

    if not (tenant_id and phone_number and content and message_id):
        logger.debug(
            "Onboarding handler: skipping event_id=%s — missing fields (tenant=%r phone=%r)",
            event.event_id,
            tenant_id,
            phone_number,
        )
        return

    async with async_session_factory.begin() as session:
        repo = TraderRepository(session)
        svc = OnboardingService(repo)
        await svc.handle(
            phone_number=phone_number,
            message=content,
            tenant_id=tenant_id,
            message_id=message_id,
            media_id=media_id,
            media_type=media_type,
        )


def register_onboarding_handler() -> asyncio.Task:
    """
    Start a background task that listens for conversation.message_saved events
    and drives the WhatsApp trader onboarding state machine.
    """
    logger.info("Registering onboarding handler (all tenants)")
    return create_global_listener_task(
        event_name=_CONVERSATION_MESSAGE_SAVED_EVENT,
        handler=handle_onboarding,
    )
