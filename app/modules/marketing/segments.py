"""
app/modules/marketing/segments.py

Segment computation engine — analyses orders, conversations, and
negotiation patterns to assign segments to each customer.

Segment types:
  Behaviour  — new_lead, browsed_only, abandoned_cart, paid_once,
               repeat_buyer, vip, lapsed
  Interest   — bought_[category], price_sensitive, premium
  Timing     — weekly, monthly, payday, weekend
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.marketing.models import CustomerListEntry
from app.modules.orders.models import Order, OrderItem, OrderState

logger = get_logger(__name__)

# ── Behaviour segment rules ──────────────────────────────────────────────────

_VIP_ORDER_THRESHOLD = 5
_VIP_SPEND_THRESHOLD = Decimal("200000")
_LAPSED_DAYS = 90  # no order in 90 days = lapsed


def _compute_behaviour_segment(
    total_orders: int,
    total_spend: Decimal,
    last_order_date: datetime | None,
    has_confirmed_unpaid: bool,
    now: datetime,
) -> str:
    """Return the single best-fit behaviour segment tag."""
    if total_orders == 0:
        if has_confirmed_unpaid:
            return "abandoned_cart"
        return "new_lead"

    if total_orders >= _VIP_ORDER_THRESHOLD or total_spend >= _VIP_SPEND_THRESHOLD:
        # VIP can still lapse
        if last_order_date and (now - last_order_date).days > _LAPSED_DAYS:
            return "lapsed"
        return "vip"

    if total_orders >= 2:
        if last_order_date and (now - last_order_date).days > _LAPSED_DAYS:
            return "lapsed"
        return "repeat_buyer"

    # total_orders == 1
    if last_order_date and (now - last_order_date).days > _LAPSED_DAYS:
        return "lapsed"
    return "paid_once"


# ── Interest segment rules ───────────────────────────────────────────────────

def _compute_interest_segments(
    order_items: list[dict],
    negotiation_count: int,
    avg_order_value: Decimal,
    trader_avg_order_value: Decimal,
) -> list[str]:
    """Return interest segment tags based on purchase history."""
    segments: list[str] = []

    # bought_[category] — group items by rough category from product names
    # For now, just track unique product names as "bought_" tags
    # Phase 2 full implementation would use the trader's business_category
    product_names = set()
    for item in order_items:
        name = item.get("product_name", "").strip().lower()
        if name:
            product_names.add(name)

    # Instead of per-product tags (too granular), count categories
    # We'll add "frequent_buyer" if they buy diverse products
    if len(product_names) >= 5:
        segments.append("diverse_buyer")

    # price_sensitive: negotiated 2+ times
    if negotiation_count >= 2:
        segments.append("price_sensitive")

    # premium: above-average spend and never negotiated
    if negotiation_count == 0 and avg_order_value > 0:
        if trader_avg_order_value > 0 and avg_order_value >= trader_avg_order_value * Decimal("1.5"):
            segments.append("premium")

    return segments


# ── Timing segment rules ─────────────────────────────────────────────────────

def _compute_timing_segments(order_dates: list[datetime]) -> list[str]:
    """Analyse order dates to detect timing patterns."""
    if len(order_dates) < 2:
        return []

    segments: list[str] = []
    sorted_dates = sorted(order_dates)

    # Weekend: >60% of orders on Fri(4), Sat(5), Sun(6)
    weekend_count = sum(1 for d in sorted_dates if d.weekday() in (4, 5, 6))
    if weekend_count / len(sorted_dates) > 0.6:
        segments.append("weekend")

    # Payday: >50% of orders between 25th and 5th of the month
    payday_count = sum(1 for d in sorted_dates if d.day >= 25 or d.day <= 5)
    if payday_count / len(sorted_dates) > 0.5:
        segments.append("payday")

    # Calculate average interval between orders
    intervals = []
    for i in range(1, len(sorted_dates)):
        delta = (sorted_dates[i] - sorted_dates[i - 1]).days
        if delta > 0:
            intervals.append(delta)

    if intervals:
        avg_interval = sum(intervals) / len(intervals)
        if avg_interval <= 10:
            segments.append("weekly")
        elif avg_interval <= 40:
            segments.append("monthly")

    return segments


# ── Main computation ─────────────────────────────────────────────────────────

async def compute_segments_for_customer(
    session: AsyncSession,
    entry: CustomerListEntry,
    now: datetime | None = None,
) -> list[str]:
    """
    Compute all segment tags for a single customer.

    Returns a list like ["vip", "weekend", "premium"].
    """
    if now is None:
        now = datetime.now(tz=timezone.utc)

    trader_phone = entry.trader_phone
    customer_phone = entry.customer_phone
    segments: list[str] = []

    # ── Fetch orders for this customer from this trader ────────────────────
    orders_result = await session.execute(
        select(Order).where(
            Order.trader_phone == trader_phone,
            Order.customer_phone == customer_phone,
        ).order_by(Order.created_at.desc())
    )
    orders = list(orders_result.scalars().all())

    # Check for abandoned cart (confirmed but never paid)
    has_confirmed_unpaid = any(
        o.state == OrderState.CONFIRMED for o in orders
    )

    # Paid orders only for spend/timing analysis
    paid_orders = [o for o in orders if o.state == OrderState.PAID]

    # ── Behaviour segment ──────────────────────────────────────────────────
    behaviour = _compute_behaviour_segment(
        total_orders=entry.total_orders,
        total_spend=entry.total_spend,
        last_order_date=entry.last_order_date,
        has_confirmed_unpaid=has_confirmed_unpaid,
        now=now,
    )
    segments.append(behaviour)

    # ── Interest segments ──────────────────────────────────────────────────
    # Get order items for this customer
    order_ids = [o.id for o in paid_orders]
    order_items: list[dict] = []
    if order_ids:
        items_result = await session.execute(
            select(OrderItem.product_name).where(
                OrderItem.order_id.in_(order_ids)
            )
        )
        order_items = [{"product_name": row[0]} for row in items_result.all()]

    # Count negotiations (approximate: orders where final amount < catalogue price)
    # For now, use 0 since we don't track negotiation events per customer yet
    # TODO: add negotiation tracking in Phase 2 refinement
    negotiation_count = 0

    # Average order value for this customer
    avg_order_value = Decimal("0")
    if paid_orders:
        total = sum((o.amount or Decimal("0")) for o in paid_orders)
        avg_order_value = total / len(paid_orders)

    # Trader's average order value (for premium detection)
    trader_avg_result = await session.execute(
        select(func.avg(Order.amount)).where(
            Order.trader_phone == trader_phone,
            Order.state == OrderState.PAID,
            Order.amount.isnot(None),
        )
    )
    trader_avg = trader_avg_result.scalar_one_or_none()
    trader_avg_order_value = Decimal(str(trader_avg)) if trader_avg else Decimal("0")

    interest = _compute_interest_segments(
        order_items=order_items,
        negotiation_count=negotiation_count,
        avg_order_value=avg_order_value,
        trader_avg_order_value=trader_avg_order_value,
    )
    segments.extend(interest)

    # ── Timing segments ────────────────────────────────────────────────────
    order_dates = [o.created_at for o in paid_orders if o.created_at]
    timing = _compute_timing_segments(order_dates)
    segments.extend(timing)

    return segments


async def recompute_all_segments(session: AsyncSession) -> int:
    """
    Recompute segments for ALL customers across all traders.

    Returns the number of customers updated.
    """
    now = datetime.now(tz=timezone.utc)

    result = await session.execute(
        select(CustomerListEntry).where(
            CustomerListEntry.opted_out == False,  # noqa: E712
        )
    )
    entries = list(result.scalars().all())

    updated = 0
    for entry in entries:
        try:
            new_segments = await compute_segments_for_customer(session, entry, now)
            entry.segments = new_segments
            entry.segments_updated_at = now
            updated += 1
        except Exception as exc:
            logger.warning(
                "Segment computation failed: trader=%s customer=%s error=%s",
                entry.trader_phone, entry.customer_phone, exc,
            )

    await session.flush()
    logger.info("Segment recompute complete: %d customers updated", updated)
    return updated
