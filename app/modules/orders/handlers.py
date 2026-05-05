"""
app/modules/orders/handlers.py

Event-driven handler for `conversation.message_saved` events (Feature 2).

Routing logic
-------------
Every inbound WhatsApp message passes through this handler AFTER the
conversation has been persisted.  Four possible actors:

1. Trader (store owner) — personal phone matches a completed Trader record.
   -> Routed to OrderService.handle_trader_command()
   -> Commands: CONFIRM/CANCEL/PAID/DELIVERED <ref>
   -> Uses trader's own tenant_id for order lookup; platform tenant for sends.

2. Customer in onboarding — sender has an active onboarding session in Redis.
   -> Skipped here; the onboarding handler owns those messages.

3. Customer sending ORDER:{slug} — message from the store cart (structured).
   -> Trader identified by slug, routing session stored in Redis.
   -> Items pre-parsed from the structured cart format (no NLP needed).
   -> Order created under trader's tenant; replies sent via platform channel.

4. Customer with existing routing session — follow-up to a cart order (YES/NO).
   -> Routing session fetched to re-identify the trader.
   -> Passed to OrderService.handle_inbound_customer_message() for confirmation.

5. Customer with no routing and no session — freeform message to platform.
   -> Prompted to visit their trader's store link.
   -> (Legacy: direct-connect traders still handled via tenant lookup.)

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
import re

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
    cache_trader_by_slug,
    cache_trader_by_tenant,
    clear_customer_routing,
    get_customer_routing,
    get_trader_by_phone_cache,
    get_trader_by_slug_cache,
    get_trader_by_tenant_cache,
    set_customer_routing,
)
import app.modules.orders.whatsapp as wa

logger = get_logger(__name__)

_CONVERSATION_MESSAGE_SAVED_EVENT = "conversation.message_saved"

# Matches the first line of a cart order: ORDER:{slug}
_ORDER_PREFIX_RE = re.compile(r"^ORDER:([A-Za-z0-9_-]+)", re.IGNORECASE)

# Matches a single cart item line: "Item Name x3" or "Item Name X3"
_CART_ITEM_RE = re.compile(r"^(.+?)\s+[xX](\d+)\s*$")


# ── Trader identity helpers ───────────────────────────────────────────────────

def _parse_catalogue(onboarding_catalogue: str | None) -> dict[str, int]:
    """Parse the JSON catalogue string stored on the Trader row."""
    if not onboarding_catalogue:
        return {}
    try:
        raw = json.loads(onboarding_catalogue)
        if isinstance(raw, dict):
            return {str(k): int(v) for k, v in raw.items() if v}
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
        "tenant_id": trader.tenant_id or "",
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
    """
    cached = await get_trader_by_phone_cache(phone_number)
    if cached is not None:
        return cached or None  # {} sentinel means "not a trader"

    async with async_session_factory() as session:
        repo = TraderRepository(session)
        trader = await repo.get_by_phone(phone_number)

    if trader is None or trader.onboarding_status != OnboardingStatus.COMPLETE:
        await cache_trader_by_phone(phone_number, {})
        return None

    data = _trader_dict(trader)
    await cache_trader_by_phone(phone_number, data)
    return data


async def _get_trader_by_tenant(tenant_id: str) -> dict | None:
    """
    Return the store owner's data for a given tenant, or None if not found.

    Used for direct-connect traders who have their own WhatsApp channel.
    """
    cached = await get_trader_by_tenant_cache(tenant_id)
    if cached is not None:
        return cached or None

    async with async_session_factory() as session:
        repo = TraderRepository(session)
        trader = await repo.get_by_tenant(tenant_id)

    if trader is None:
        await cache_trader_by_tenant(tenant_id, {})
        return None

    data = _trader_dict(trader)
    await cache_trader_by_tenant(tenant_id, data)
    return data


async def _get_trader_by_slug(store_slug: str) -> dict | None:
    """
    Return trader data for a store slug, or None if not found / not complete.

    Checks Redis first (TTL 1 h), falls back to the database.
    """
    cached = await get_trader_by_slug_cache(store_slug)
    if cached is not None:
        return cached or None  # {} sentinel means "not found"

    async with async_session_factory() as session:
        repo = TraderRepository(session)
        trader = await repo.get_by_slug(store_slug)

    if trader is None or trader.onboarding_status != OnboardingStatus.COMPLETE:
        await cache_trader_by_slug(store_slug, {})
        return None

    data = _trader_dict(trader)
    await cache_trader_by_slug(store_slug, data)
    return data


# ── Cart message parsing ──────────────────────────────────────────────────────

def _parse_cart_message(message: str) -> tuple[str | None, list[dict]]:
    """
    Parse an ORDER:{slug} cart message into (slug, cart_items).

    Expected format (generated by StoreCatalogue):
        ORDER:mama-caro-provisions
        Garri x2
        Rice x1

    Returns (slug, [{name, qty}, ...]) on success, or (None, []) if the
    message does not match the ORDER: prefix.
    """
    lines = [line.strip() for line in message.strip().splitlines() if line.strip()]
    if not lines:
        return None, []

    m = _ORDER_PREFIX_RE.match(lines[0])
    if not m:
        return None, []

    slug = m.group(1).lower()
    items: list[dict] = []

    for line in lines[1:]:
        item_match = _CART_ITEM_RE.match(line)
        if item_match:
            name = item_match.group(1).strip()
            qty = int(item_match.group(2))
            if name and qty > 0:
                items.append({"name": name, "qty": qty})

    return slug, items


# ── Audio transcription ───────────────────────────────────────────────────────

async def _transcribe_audio(
    media_id: str,
    media_type: str,
    tenant_id: str,
) -> str:
    """
    Download and transcribe a WhatsApp voice note.

    Returns the transcription text, or an empty string on failure.
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


# ── Image download ───────────────────────────────────────────────────────────

async def _download_image(
    media_id: str,
    tenant_id: str,
) -> bytes | None:
    """
    Download a WhatsApp image.

    Returns the raw bytes, or None on failure.
    """
    try:
        from app.modules.onboarding.media import download_whatsapp_media

        async with async_session_factory() as session:
            channel_repo = ChannelRepository(session)
            return await download_whatsapp_media(
                media_id=media_id,
                tenant_id=tenant_id,
                channel_repo=channel_repo,
            )
    except Exception as exc:
        logger.warning(
            "Image download failed media_id=%s: %s", media_id, exc
        )
        return None


# ── Main event handler ────────────────────────────────────────────────────────

async def handle_order_intent(event: Event) -> None:
    """
    Route a conversation.message_saved event to the appropriate order handler.

    Steps:
    1. Validate required fields; drop malformed events.
    2. Skip non-WhatsApp channels.
    3. Skip senders in an active onboarding session.
    4. If sender is an onboarded trader -> handle_trader_command() using the
       trader's own tenant_id; platform tenant for outbound channel.
    5. If message starts with ORDER:{slug} -> identify trader by slug, store
       routing session, parse cart items, create order via handle_cart_order().
    6. If customer has an active routing session -> load routing context,
       pass to handle_inbound_customer_message() for YES/NO handling.
    7. If tenant has a direct-connect trader -> legacy single-trader path.
    8. Otherwise -> prompt customer to use the store link.
    """
    payload = event.payload
    platform_tenant_id: str = event.tenant_id
    channel: str = payload.get("channel", "")

    if channel != "whatsapp":
        return

    sender_phone: str = payload.get("sender_identifier") or payload.get("customer_identifier", "")
    content: str = payload.get("content", "")
    message_id: str = payload.get("id", "")
    conversation_id: str = payload.get("conversation_id", "")
    media_id: str | None = payload.get("media_id")
    media_type: str | None = payload.get("media_type")

    if not (platform_tenant_id and sender_phone and message_id and conversation_id):
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

    # ── Skip onboarding trigger keywords from unknown senders ─────────────
    # Both handlers receive events simultaneously. For a brand-new user the
    # onboarding state may not yet exist when this handler checks, but the
    # onboarding handler will create it. Avoid the duplicate "no context"
    # reply by recognising trigger keywords here and yielding to onboarding.
    _ONBOARDING_TRIGGERS = {"start", "register", "join", "hi", "hello", "hey"}
    if content.strip().lower() in _ONBOARDING_TRIGGERS:
        async with async_session_factory.begin() as session:
            trader_repo = TraderRepository(session)
            existing_trader = await trader_repo.get_by_phone(sender_phone)
        if existing_trader is None:
            logger.debug(
                "Order handler: sender=%s sent onboarding trigger %r — yielding to onboarding, event_id=%s",
                sender_phone,
                content.strip(),
                event.event_id,
            )
            return

    # ── Handle audio (voice note orders) ─────────────────────────────────────
    message = content
    if media_id and media_type and media_type.startswith("audio/"):
        transcribed = await _transcribe_audio(media_id, media_type, platform_tenant_id)
        if transcribed:
            message = transcribed
            logger.info(
                "Order handler: audio transcribed %d chars sender=%s",
                len(transcribed),
                sender_phone,
            )

    # ── Handle image (product inquiry) ────────────────────────────────────────
    is_image = (
        media_id
        and media_type
        and media_type.startswith("image/")
        and message == "[image]"
    )
    image_bytes: bytes | None = None
    if is_image:
        image_bytes = await _download_image(media_id, platform_tenant_id)
        if image_bytes:
            logger.info(
                "Order handler: image downloaded %d bytes sender=%s",
                len(image_bytes),
                sender_phone,
            )

    # ── Route: trader command? ────────────────────────────────────────────────
    trader_data = await _get_trader_by_phone(sender_phone)

    if trader_data:
        # Sender is a store owner — handle as a trader command.
        # Use trader's own tenant_id for order DB lookups; platform tenant for sends.
        trader_tenant_id = trader_data.get("tenant_id") or platform_tenant_id
        logger.info(
            "Order handler: trader command sender=%s tenant=%s event_id=%s",
            sender_phone,
            trader_tenant_id,
            event.event_id,
        )
        async with async_session_factory.begin() as session:
            svc = OrderService(session)
            await svc.handle_trader_command(
                tenant_id=trader_tenant_id,
                trader_phone=sender_phone,
                message=message,
                message_id=message_id,
                trader=trader_data,
                channel_tenant_id=platform_tenant_id,
                image_bytes=image_bytes,
            )
        return

    # ── Route: ORDER:{slug} cart message ─────────────────────────────────────
    slug, cart_items = _parse_cart_message(message)

    if slug is not None:
        store_trader = await _get_trader_by_slug(slug)

        if store_trader is None or not store_trader.get("tenant_id"):
            logger.warning(
                "Order handler: ORDER:%s — no completed trader found, event_id=%s",
                slug,
                event.event_id,
            )
            # Silently drop — store may be misconfigured
            return

        trader_tenant_id = store_trader["tenant_id"]

        # Store a routing session so subsequent YES/NO replies reach this trader
        await set_customer_routing(
            sender_phone,
            {
                "slug": slug,
                "tenant_id": trader_tenant_id,
                "trader_phone": store_trader.get("phone_number", ""),
                "trader_name": store_trader.get("business_name", ""),
                "catalogue": store_trader.get("catalogue", {}),
            },
        )

        logger.info(
            "Order handler: cart order sender=%s slug=%s tenant=%s event_id=%s",
            sender_phone,
            slug,
            trader_tenant_id,
            event.event_id,
        )

        if not cart_items:
            # ORDER: prefix but no parseable items — show the unknown prompt
            async with async_session_factory.begin() as session:
                svc = OrderService(session)
                await svc._reply(  # noqa: SLF001  (internal helper)
                    phone=sender_phone,
                    tenant_id=trader_tenant_id,
                    event_id=f"order.cart_empty.{message_id}",
                    text=wa.unknown_order_prompt(),
                    channel_tenant_id=platform_tenant_id,
                )
            return

        async with async_session_factory.begin() as session:
            svc = OrderService(session)
            await svc.handle_cart_order(
                tenant_id=trader_tenant_id,
                conversation_id=conversation_id,
                customer_phone=sender_phone,
                message_id=message_id,
                trader=store_trader,
                cart_items=cart_items,
                channel_tenant_id=platform_tenant_id,
            )
        return

    # ── Route: customer with existing routing session ─────────────────────────
    routing = await get_customer_routing(sender_phone)

    if routing:
        trader_tenant_id = routing["tenant_id"]
        store_trader = {
            "tenant_id": trader_tenant_id,
            "phone_number": routing.get("trader_phone", ""),
            "business_name": routing.get("trader_name", ""),
            "business_category": "",
            "catalogue": routing.get("catalogue", {}),
        }
        logger.info(
            "Order handler: routed customer=%s to slug=%s event_id=%s",
            sender_phone,
            routing.get("slug"),
            event.event_id,
        )
        async with async_session_factory.begin() as session:
            svc = OrderService(session)
            if image_bytes is not None:
                await svc.handle_image_inquiry(
                    tenant_id=trader_tenant_id,
                    conversation_id=conversation_id,
                    customer_phone=sender_phone,
                    message=message,
                    message_id=message_id,
                    image_bytes=image_bytes,
                    media_id=media_id,
                    trader=store_trader,
                    channel_tenant_id=platform_tenant_id,
                )
            else:
                await svc.handle_inbound_customer_message(
                    tenant_id=trader_tenant_id,
                    conversation_id=conversation_id,
                    customer_phone=sender_phone,
                    message=message,
                    message_id=message_id,
                    trader=store_trader,
                    channel_tenant_id=platform_tenant_id,
                )
        return

    # ── Route: direct-connect trader (legacy / single-tenant mode) ───────────
    store_trader = await _get_trader_by_tenant(platform_tenant_id)

    if store_trader:
        logger.info(
            "Order handler: direct customer message sender=%s event_id=%s",
            sender_phone,
            event.event_id,
        )
        async with async_session_factory.begin() as session:
            svc = OrderService(session)
            if image_bytes is not None:
                await svc.handle_image_inquiry(
                    tenant_id=platform_tenant_id,
                    conversation_id=conversation_id,
                    customer_phone=sender_phone,
                    message=message,
                    message_id=message_id,
                    image_bytes=image_bytes,
                    media_id=media_id,
                    trader=store_trader,
                )
            else:
                await svc.handle_inbound_customer_message(
                    tenant_id=platform_tenant_id,
                    conversation_id=conversation_id,
                    customer_phone=sender_phone,
                    message=message,
                    message_id=message_id,
                    trader=store_trader,
                )
        return

    # ── No trader context — prompt customer to use store link ─────────────────
    logger.debug(
        "Order handler: no trader context for sender=%s event_id=%s — sending store prompt",
        sender_phone,
        event.event_id,
    )
    async with async_session_factory.begin() as session:
        svc = OrderService(session)
        await svc._reply(  # noqa: SLF001
            phone=sender_phone,
            tenant_id=platform_tenant_id,
            event_id=f"order.no_context.{message_id}",
            text=wa.store_order_prompt(),
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
