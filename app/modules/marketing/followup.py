"""
app/modules/marketing/followup.py

Smart follow-up system — tracks customer interest and auto-sends
a single warm follow-up 24h later if no order was placed.

Interest events are created when a customer:
  - Asks about a product price (price inquiry)
  - Sends a product photo (image inquiry)
  - Starts an order but cancels (order cancelled)

The scheduler job (_send_follow_ups in scheduler.py) runs hourly
during business hours and processes events that are 24h+ old.
"""

from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import (
    Boolean, DateTime, Index, Integer,
    Numeric, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.base import TenantModel


# ── Interest Event Model ─────────────────────────────────────────────────────


class InterestType(StrEnum):
    PRICE_INQUIRY = "price_inquiry"
    IMAGE_INQUIRY = "image_inquiry"
    ORDER_CANCELLED = "order_cancelled"


class InterestEvent(TenantModel):
    """
    Tracks a customer's interest in a specific product.
    One follow-up is sent per event if no order is placed within 24h.
    """
    __tablename__ = "interest_events"
    __table_args__ = (
        Index("ix_interest_events_trader", "trader_phone"),
        Index("ix_interest_events_pending", "followed_up", "created_at"),
    )

    trader_phone: Mapped[str] = mapped_column(String(40), nullable=False)
    customer_phone: Mapped[str] = mapped_column(String(40), nullable=False)
    customer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    product_name: Mapped[str] = mapped_column(String(300), nullable=False)
    price: Mapped[int | None] = mapped_column(Integer, nullable=True)  # in Naira
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)

    # Follow-up tracking
    followed_up: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    followed_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Conversion tracking
    converted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    order_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


# ── Service ──────────────────────────────────────────────────────────────────


from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.logging import get_logger

logger = get_logger(__name__)


async def log_interest(
    db: AsyncSession,
    *,
    tenant_id: str,
    trader_phone: str,
    customer_phone: str,
    customer_name: str | None,
    product_name: str,
    price: int | None,
    event_type: str,
) -> InterestEvent:
    """Log a customer interest event. Deduplicates by product within 48h."""
    from datetime import timedelta

    # Check for recent duplicate (same customer + product within 48h)
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=48)
    existing = (await db.execute(
        select(InterestEvent).where(
            InterestEvent.trader_phone == trader_phone,
            InterestEvent.customer_phone == customer_phone,
            InterestEvent.product_name == product_name,
            InterestEvent.created_at > cutoff,
        ).limit(1)
    )).scalar_one_or_none()

    if existing:
        return existing

    event = InterestEvent(
        tenant_id=tenant_id,
        trader_phone=trader_phone,
        customer_phone=customer_phone,
        customer_name=customer_name,
        product_name=product_name,
        price=price,
        event_type=event_type,
    )
    db.add(event)
    await db.flush()
    logger.info(
        "Interest logged: trader=%s customer=%s product=%s type=%s",
        trader_phone, customer_phone, product_name, event_type,
    )
    return event


async def mark_converted(
    db: AsyncSession,
    *,
    trader_phone: str,
    customer_phone: str,
    product_name: str,
    order_id: str,
) -> None:
    """Mark interest events as converted when the customer places an order."""
    await db.execute(
        update(InterestEvent)
        .where(
            InterestEvent.trader_phone == trader_phone,
            InterestEvent.customer_phone == customer_phone,
            InterestEvent.product_name == product_name,
            InterestEvent.converted == False,  # noqa: E712
        )
        .values(converted=True, order_id=order_id)
    )


async def get_pending_followups(
    db: AsyncSession,
    *,
    min_age_hours: int = 24,
    limit: int = 50,
) -> list[InterestEvent]:
    """
    Find interest events that need a follow-up:
    - 24h+ old
    - Not yet followed up
    - Not converted to an order
    """
    from datetime import timedelta

    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=min_age_hours)
    result = await db.execute(
        select(InterestEvent).where(
            InterestEvent.followed_up == False,  # noqa: E712
            InterestEvent.converted == False,  # noqa: E712
            InterestEvent.created_at <= cutoff,
        )
        .order_by(InterestEvent.created_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def mark_followed_up(db: AsyncSession, event_id: str) -> None:
    """Mark an interest event as followed up."""
    await db.execute(
        update(InterestEvent)
        .where(InterestEvent.id == event_id)
        .values(
            followed_up=True,
            followed_up_at=datetime.now(tz=timezone.utc),
        )
    )
