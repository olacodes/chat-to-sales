"""
app/modules/orders/handlers.py

Event-driven handler for `conversation.message_saved` events (Feature 2).

Routing logic
-------------
Every inbound WhatsApp message passes through this handler AFTER the
conversation has been persisted.  Three possible actors:

1. Trader (store owner) — personal phone matches a completed Trader record.
   -> Routed to OrderService.handle_trader_command()
   -> Commands: CONFIRM/CANCEL/PAID/DELIVERED <ref>

2. Customer in onboarding — sender has an active onboarding session in Redis.
   -> Skipped here; the onboarding handler owns those messages.

3. Customer (everyone else) — routed to OrderService.handle_inbound_customer_message()
   -> NLP parses the message and manages the order conversation.

Audio (voice note) messages
---------------------------
If media_type starts with "audio/" the raw bytes are downloaded and transcribed
via OpenAI Whisper before the text is parsed for order intent.

Wiring
------
register_order_intent_handler() is already called in app/main.py's lifespan.
No changes to main.py are needed.
"""

import asyncio
import json

from app.core.logging import get_logger
from app.infra.database import async_session_factory
from app.infra.event_bus import Event, create_global_listener_task
from app.modules.channels.repository import ChannelRepository
from app.modules.onboarding.models import OnboardingStatus
from app.modules.onboarding.repository import TraderRepository
from app.modules.onboarding.session import get_state as get_onboarding_state
from app.modules.orders.service import OrderService
from app.modules.orders.session import (
    cache_trader_by_phone,
    cache_trader_by_tenant,
    get_trader_by_phone_cache,
    get_trader_by_tenant_cache,
)

logger = get_logger(__name__)

_CONVERSATION_MESSAGE_SAVED_EVENT = "conversation.message_saved"


# ── Trader identity lookup ────────────────────────────────────────────────────

def _parse_catalogue(onboarding_catalogue: str | None) -> dict[str, int]:
    """Parse the JSON catalogue string stored on the Trader row."""
    if not onboarding_catalogue:
        return {}
    try:
        raw = json.loads(onboarding_catalogue)
        if isinstance(raw, dict):
            return {str(k): int(v) for k, v in raw.items() if v}
        # List format: [{name, price}, ...]
        if isinstance(raw, list):
            return {
                str(item.get("name", "")): int(item.get("price", 0))
                for item in raw
                if isinstance(item, dict) and item.get("name") and item.get("price")
            }
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return {}


def _trader_dict(trader) -> dict:
    """Convert a Trader ORM row to the plain dict used by the service."""
    return {
        "phone_number": trader.phone_number,
        "business_name": trader.business_name or "",
        "business_category": trader.business_category or "",
        "store_slug": trader.store_slug or "",
        "catalogue": _parse_catalogue(trader.onboarding_catalogue),
    }


async def _get_trader_by_phone(phone_number: str) -> dict | None:
    """
    Return trader data for a phone number, or None if not an onboarded trader.

    Checks Redis first (TTL 1 h), falls back to the database.
    Caches the result on a DB hit.
    """
    cached = await get_trader_by_phone_cache(phone_number)
    if cached is not None:
        return cached  # may be {} sentinel meaning "not a trader"

    async with async_session_factory() as session:
        repo = TraderRepository(session)
        trader = await repo.get_by_phone(phone_number)

    if trader is None or trader.onboarding_status != OnboardingStatus.COMPLETE:
        # Cache a sentinel so we don't hit the DB again for 1 h
        await cache_trader_by_phone(phone_number, {})
        return None

    data = _trader_dict(trader)
    await cache_trader_by_phone(phone_number, data)
    return data


async def _get_trader_by_tenant(tenant_id: str) -> dict | None:
    """
    Return the store owner's data for a given tenant, or None if not found.

    Used when a customer messages — we need the trader's name and catalogue
    to show prices and send the trader a notification.
    """
    cached = await get_trader_by_tenant_cache(tenant_id)
    if cached is not None:
        return cached or None  # {} sentinel means no trader found

    async with async_session_factory() as session:
        repo = TraderRepository(session)
        trader = await repo.get_by_tenant(tenant_id)

    if trader is None:
        await cache_trader_by_tenant(tenant_id, {})
        return None

    data = _trader_dict(trader)
    await cache_trader_by_tenant(tenant_id, data)
    return data


# ── Audio transcription ───────────────────────────────────────────────────────

async def _transcribe_audio(
    media_id: str,
    media_type: str,
    tenant_id: str,
) -> str:
    """
    Download and transcribe a WhatsApp voice note.

    Returns the transcription text, or an empty string on failure.
    Imports media helpers lazily to keep startup fast.
    """
    try:
        from app.modules.onboarding.media import (
            download_whatsapp_media,
            transcribe_audio_bytes,
        )

        async with async_session_factory() as session:
            channel_repo = ChannelRepository(session)
            audio_bytes = await download_whatsapp_media(
                media_id=media_id,
                tenant_id=tenant_id,
                channel_repo=channel_repo,
            )
        return await transcribe_audio_bytes(audio_bytes, mime_type=media_type)
    except Exception as exc:
        logger.warning(
            "Audio transcription failed media_id=%s: %s", media_id, exc
        )
        return ""


# ── Main event handler ────────────────────────────────────────────────────────

async def handle_order_intent(event: Event) -> None:
    """
    Route a conversation.message_saved event to the appropriate order handler.

    Steps:
    1. Validate required fields; drop malformed events.
    2. Skip non-WhatsApp channels.
    3. Skip senders in an active onboarding session (handled by onboarding module).
    4. If sender is an onboarded trader -> handle_trader_command().
    5. If sender is a customer -> load the tenant's trader, then handle_inbound_customer_message().
    6. If the tenant has no completed trader -> skip silently (store not yet set up).
    """
    payload = event.payload
    tenant_id: str = event.tenant_id
    channel: str = payload.get("channel", "")

    if channel != "whatsapp":
        return

    sender_phone: str = payload.get("sender_identifier") or payload.get("customer_identifier", "")
    content: str = payload.get("content", "")
    message_id: str = payload.get("id", "")
    conversation_id: str = payload.get("conversation_id", "")
    media_id: str | None = payload.get("media_id")
    media_type: str | None = payload.get("media_type")

    if not (tenant_id and sender_phone and message_id and conversation_id):
        logger.debug(
            "Order handler: skipping event_id=%s — missing fields", event.event_id
        )
        return

    # ── Skip senders actively in onboarding ───────────────────────────────────
    onboarding_state = await get_onboarding_state(sender_phone)
    if onboarding_state is not None:
        logger.debug(
            "Order handler: sender=%s is in onboarding — skipping event_id=%s",
            sender_phone,
            event.event_id,
        )
        return

    # ── Handle audio (voice note orders) ─────────────────────────────────────
    message = content
    if media_id and media_type and media_type.startswith("audio/"):
        transcribed = await _transcribe_audio(media_id, media_type, tenant_id)
        if transcribed:
            message = transcribed
            logger.info(
                "Order handler: audio transcribed %d chars sender=%s",
                len(transcribed),
                sender_phone,
            )
        else:
            # Could not transcribe — still try with the "[audio]" sentinel
            # so the NLP can return an appropriate prompt to the customer.
            pass

    # ── Route: trader vs customer ─────────────────────────────────────────────
    trader_data = await _get_trader_by_phone(sender_phone)

    if trader_data:
        # Sender is the store owner — handle as a trader command
        logger.info(
            "Order handler: trader command sender=%s event_id=%s",
            sender_phone,
            event.event_id,
        )
        async with async_session_factory.begin() as session:
            svc = OrderService(session)
            await svc.handle_trader_command(
                tenant_id=tenant_id,
                trader_phone=sender_phone,
                message=message,
                message_id=message_id,
                trader=trader_data,
            )
        return

    # Sender is a customer — load the tenant's trader for context
    store_trader = await _get_trader_by_tenant(tenant_id)
    if store_trader is None:
        logger.debug(
            "Order handler: no completed trader for tenant=%s — skipping event_id=%s",
            tenant_id,
            event.event_id,
        )
        return

    logger.info(
        "Order handler: customer message sender=%s event_id=%s",
        sender_phone,
        event.event_id,
    )
    async with async_session_factory.begin() as session:
        svc = OrderService(session)
        await svc.handle_inbound_customer_message(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            customer_phone=sender_phone,
            message=message,
            message_id=message_id,
            trader=store_trader,
        )


# ── Registration ──────────────────────────────────────────────────────────────

def register_order_intent_handler() -> asyncio.Task:
    """
    Start a single background task that consumes conversation.message_saved
    events from all tenants and drives the order management flow.
    """
    logger.info("Registering order-intent handler (all tenants)")
    return create_global_listener_task(
        event_name=_CONVERSATION_MESSAGE_SAVED_EVENT,
        handler=handle_order_intent,
    )


def register_credit_sale_status_handler() -> asyncio.Task:
    """
    Start a background task that listens for credit_sale.status_changed events
    and completes the linked order when the credit sale is resolved.
    """
    from app.infra.event_bus import create_global_listener_task as _cgl

    _CREDIT_SALE_STATUS_CHANGED_EVENT = "credit_sale.status_changed"
    _RESOLVING_STATUSES = frozenset({"settled", "written_off"})

    async def handle_credit_sale_status_changed(evt: Event) -> None:
        p = evt.payload
        t_id: str = evt.tenant_id
        order_id: str = p.get("order_id", "")
        new_status: str = p.get("new_status", "")
        if not (order_id and t_id and new_status):
            return
        if new_status not in _RESOLVING_STATUSES:
            return
        logger.info(
            "CreditSaleStatus: resolved status=%s order_id=%s", new_status, order_id
        )
        async with async_session_factory.begin() as session:
            svc = OrderService(session)
            order = await svc.handle_credit_sale_resolved(
                order_id=order_id, tenant_id=t_id
            )
        if order is None:
            logger.warning("CreditSaleStatus: transition skipped order_id=%s", order_id)
        else:
            logger.info("CreditSaleStatus: order COMPLETED order_id=%s", order.id)

    logger.info("Registering credit_sale.status_changed handler (all tenants)")
    return _cgl(
        event_name=_CREDIT_SALE_STATUS_CHANGED_EVENT,
        handler=handle_credit_sale_status_changed,
    )
