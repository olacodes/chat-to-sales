"""
app/modules/orders/session.py

Redis-backed state for in-flight customer order conversations, and a fast
trader-identity cache to avoid a DB round-trip on every customer message.

Key schema
----------
  order:session:{tenant_id}:{customer_phone}  ->  JSON  customer order state
  trader:phone:{phone_number}                 ->  JSON  trader identity record
  trader:tenant:{tenant_id}                   ->  JSON  trader for a given tenant
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
