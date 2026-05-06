"""
app/modules/orders/session.py

Redis-backed state for in-flight customer order conversations, and a fast
trader-identity cache to avoid a DB round-trip on every customer message.

Key schema
----------
  order:session:{tenant_id}:{customer_phone}  ->  JSON  customer order state
  trader:phone:{phone_number}                 ->  JSON  trader identity record
  trader:tenant:{tenant_id}                   ->  JSON  trader for a given tenant
  trader:slug:{store_slug}                    ->  JSON  trader for a given store slug
  customer:routing:{customer_phone}           ->  JSON  active trader context for a customer
"""

import json
from typing import Any

from app.infra.cache import get_redis

_SESSION_PREFIX = "order:session"
_SESSION_TTL = 24 * 60 * 60      # 24 hours

_TRADER_PHONE_PREFIX = "trader:phone"
_TRADER_TENANT_PREFIX = "trader:tenant"
_TRADER_TTL = 60 * 60             # 1 hour, refreshed on each cache hit

# ── Session state labels ──────────────────────────────────────────────────────

AWAITING_CUSTOMER_CONFIRMATION = "awaiting_customer_confirmation"
AWAITING_CLARIFICATION = "awaiting_clarification"

# ── Customer order session ────────────────────────────────────────────────────


def _session_key(tenant_id: str, customer_phone: str) -> str:
    return f"{_SESSION_PREFIX}:{tenant_id}:{customer_phone}"


async def get_order_session(tenant_id: str, customer_phone: str) -> dict[str, Any] | None:
    """Return the active order session for a customer, or None."""
    raw = await get_redis().get(_session_key(tenant_id, customer_phone))
    return json.loads(raw) if raw else None


async def set_order_session(
    tenant_id: str,
    customer_phone: str,
    data: dict[str, Any],
) -> None:
    """Persist the customer's order session with a 24-hour TTL."""
    await get_redis().setex(
        _session_key(tenant_id, customer_phone),
        _SESSION_TTL,
        json.dumps(data),
    )


async def clear_order_session(tenant_id: str, customer_phone: str) -> None:
    """Delete the customer's order session (order placed or cancelled)."""
    await get_redis().delete(_session_key(tenant_id, customer_phone))


# ── Trader identity cache (by phone number) ───────────────────────────────────


def _trader_phone_key(phone_number: str) -> str:
    return f"{_TRADER_PHONE_PREFIX}:{phone_number}"


async def get_trader_by_phone_cache(phone_number: str) -> dict[str, Any] | None:
    """
    Return cached trader record for a phone number, or None on cache miss.

    Used to quickly determine whether an inbound message is from the store
    owner (trader) rather than a customer.
    """
    raw = await get_redis().get(_trader_phone_key(phone_number))
    return json.loads(raw) if raw else None


async def cache_trader_by_phone(phone_number: str, data: dict[str, Any]) -> None:
    """Cache trader data keyed by personal phone number."""
    await get_redis().setex(_trader_phone_key(phone_number), _TRADER_TTL, json.dumps(data))


# ── Trader identity cache (by tenant_id) ──────────────────────────────────────


def _trader_tenant_key(tenant_id: str) -> str:
    return f"{_TRADER_TENANT_PREFIX}:{tenant_id}"


async def get_trader_by_tenant_cache(tenant_id: str) -> dict[str, Any] | None:
    """
    Return cached trader record for a tenant, or None on cache miss.

    Used when a customer message arrives — we need the store owner's data
    (name, catalogue) to show prices and send trader notifications.
    """
    raw = await get_redis().get(_trader_tenant_key(tenant_id))
    return json.loads(raw) if raw else None


async def cache_trader_by_tenant(tenant_id: str, data: dict[str, Any]) -> None:
    """Cache trader data keyed by tenant_id."""
    await get_redis().setex(_trader_tenant_key(tenant_id), _TRADER_TTL, json.dumps(data))


# ── Trader identity cache (by store slug) ─────────────────────────────────────

_TRADER_SLUG_PREFIX = "trader:slug"


def _trader_slug_key(store_slug: str) -> str:
    return f"{_TRADER_SLUG_PREFIX}:{store_slug}"


async def get_trader_by_slug_cache(store_slug: str) -> dict[str, Any] | None:
    """Return cached trader record for a store slug, or None on cache miss."""
    raw = await get_redis().get(_trader_slug_key(store_slug))
    return json.loads(raw) if raw else None


async def cache_trader_by_slug(store_slug: str, data: dict[str, Any]) -> None:
    """Cache trader data keyed by store slug."""
    await get_redis().setex(_trader_slug_key(store_slug), _TRADER_TTL, json.dumps(data))


# ── Customer → trader routing session ─────────────────────────────────────────

_CUSTOMER_ROUTING_PREFIX = "customer:routing"
_CUSTOMER_ROUTING_TTL = 4 * 60 * 60  # 4 hours


def _customer_routing_key(phone: str) -> str:
    return f"{_CUSTOMER_ROUTING_PREFIX}:{phone}"


async def get_customer_routing(phone: str) -> dict[str, Any] | None:
    """
    Return the active routing record for a customer, or None.

    Set when a customer sends ORDER:{slug}; refreshed on each interaction.
    Allows subsequent messages (YES/NO) to reach the same trader's session.

    Routing dict keys: tenant_id, trader_phone, trader_name, catalogue, slug
    """
    raw = await get_redis().get(_customer_routing_key(phone))
    return json.loads(raw) if raw else None


async def set_customer_routing(phone: str, data: dict[str, Any]) -> None:
    """Map customer phone -> trader routing context with a 4-hour TTL."""
    await get_redis().setex(_customer_routing_key(phone), _CUSTOMER_ROUTING_TTL, json.dumps(data))


async def clear_customer_routing(phone: str) -> None:
    """Remove the customer routing record (order completed, cancelled, or expired)."""
    await get_redis().delete(_customer_routing_key(phone))


# ── Pending image inquiries (per-customer, supports concurrent photos) ────

_IMAGE_INQUIRY_PREFIX = "image:inquiry"
_IMAGE_INQUIRY_INDEX = "image:inquiries"
_IMAGE_INQUIRY_TTL = 24 * 60 * 60  # 24 hours


def _image_inquiry_key(trader_phone: str, customer_phone: str) -> str:
    return f"{_IMAGE_INQUIRY_PREFIX}:{trader_phone}:{customer_phone}"


def _image_inquiry_index_key(trader_phone: str) -> str:
    return f"{_IMAGE_INQUIRY_INDEX}:{trader_phone}"


async def get_pending_image_inquiry(trader_phone: str) -> dict[str, Any] | None:
    """
    Return the most recent pending image inquiry for this trader, or None.

    When multiple customers have sent photos, returns the latest one
    (the one the trader is most likely replying to).
    """
    redis = get_redis()
    index_key = _image_inquiry_index_key(trader_phone)
    members = await redis.smembers(index_key)
    if not members:
        return None

    # Find the most recent inquiry that still has data
    for customer_phone in sorted(members, reverse=True):
        cp = customer_phone if isinstance(customer_phone, str) else customer_phone.decode()
        raw = await redis.get(_image_inquiry_key(trader_phone, cp))
        if raw:
            return json.loads(raw)
        # Stale index entry — clean it up
        await redis.srem(index_key, customer_phone)

    return None


async def set_pending_image_inquiry(
    trader_phone: str, data: dict[str, Any]
) -> None:
    """
    Store a pending image inquiry keyed by trader + customer phone.

    Multiple customers can have concurrent pending inquiries for the
    same trader — each gets its own Redis key.
    """
    customer_phone: str = data.get("customer_phone", "")
    if not customer_phone:
        return

    redis = get_redis()
    key = _image_inquiry_key(trader_phone, customer_phone)
    index_key = _image_inquiry_index_key(trader_phone)

    await redis.setex(key, _IMAGE_INQUIRY_TTL, json.dumps(data))
    await redis.sadd(index_key, customer_phone)
    await redis.expire(index_key, _IMAGE_INQUIRY_TTL)


async def clear_pending_image_inquiry(
    trader_phone: str, customer_phone: str | None = None
) -> None:
    """
    Remove a pending image inquiry after the trader replies.

    If customer_phone is given, removes only that customer's inquiry.
    If None, removes the most recent one (backwards compat).
    """
    redis = get_redis()
    index_key = _image_inquiry_index_key(trader_phone)

    if customer_phone:
        await redis.delete(_image_inquiry_key(trader_phone, customer_phone))
        await redis.srem(index_key, customer_phone)
    else:
        # Legacy: clear the most recent
        members = await redis.smembers(index_key)
        if members:
            cp = sorted(members, reverse=True)[0]
            cp_str = cp if isinstance(cp, str) else cp.decode()
            await redis.delete(_image_inquiry_key(trader_phone, cp_str))
            await redis.srem(index_key, cp)


async def count_pending_image_inquiries(trader_phone: str) -> int:
    """Return the number of pending image inquiries for this trader."""
    redis = get_redis()
    return await redis.scard(_image_inquiry_index_key(trader_phone))


# ── Trader command session (multi-step catalogue flows) ──────────────────────

_TRADER_SESSION_PREFIX = "trader:session"
_TRADER_SESSION_TTL = 10 * 60  # 10 minutes

# Trader session states
TRADER_AWAITING_ADD = "awaiting_add"
TRADER_AWAITING_REMOVE = "awaiting_remove"
TRADER_AWAITING_PRICE_SELECT = "awaiting_price_select"
TRADER_AWAITING_PRICE_VALUE = "awaiting_price_value"
TRADER_AWAITING_PRICELIST_PHOTO = "awaiting_pricelist_photo"
TRADER_AWAITING_PRICELIST_CONFIRM = "awaiting_pricelist_confirm"


def _trader_session_key(phone: str) -> str:
    return f"{_TRADER_SESSION_PREFIX}:{phone}"


async def get_trader_session(phone: str) -> dict[str, Any] | None:
    """Return the active trader command session, or None."""
    raw = await get_redis().get(_trader_session_key(phone))
    return json.loads(raw) if raw else None


async def set_trader_session(phone: str, data: dict[str, Any]) -> None:
    """Store a trader command session with a 10-minute TTL."""
    await get_redis().setex(
        _trader_session_key(phone), _TRADER_SESSION_TTL, json.dumps(data)
    )


async def clear_trader_session(phone: str) -> None:
    """Remove the trader command session."""
    await get_redis().delete(_trader_session_key(phone))
