"""
app/modules/marketing/models.py

Database models for the segmented broadcast system.

CustomerListEntry — one row per customer per trader (auto-populated from orders)
Broadcast — one row per broadcast sent by a trader
BroadcastRecipient — one row per recipient per broadcast (tracks delivery)
"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, Integer,
    Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models.base import BaseModel, TenantModel


# ── Customer List ────────────────────────────────────────────────────────────


class CustomerListEntry(TenantModel):
    """
    One row per customer per trader. Auto-populated from orders + conversations.
    """
    __tablename__ = "customer_list"
    __table_args__ = (
        UniqueConstraint("trader_phone", "customer_phone", name="uq_customer_list_trader_customer"),
        Index("ix_customer_list_trader", "trader_phone"),
    )

    trader_phone: Mapped[str] = mapped_column(String(40), nullable=False)
    customer_phone: Mapped[str] = mapped_column(String(40), nullable=False)
    customer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Aggregates (updated on each order)
    total_orders: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    total_spend: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"), server_default="0")
    first_order_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_order_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Opt-out
    opted_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Last marketing message sent (for 7-day cap)
    last_broadcast_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Computed segments (recomputed nightly)
    # e.g. ["vip", "weekend", "bought_phones", "premium"]
    segments: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)
    segments_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── Broadcast ────────────────────────────────────────────────────────────────


class BroadcastStatus(StrEnum):
    DRAFT = "draft"
    SENDING = "sending"
    SENT = "sent"
    PAUSED = "paused"
    FAILED = "failed"


class Broadcast(TenantModel):
    """
    One row per broadcast message sent by a trader.
    """
    __tablename__ = "broadcasts"
    __table_args__ = (
        Index("ix_broadcasts_trader", "trader_phone"),
    )

    trader_phone: Mapped[str] = mapped_column(String(40), nullable=False)
    segment: Mapped[str] = mapped_column(String(100), nullable=False)
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    original_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # trader's raw input before Claude rewrite

    # Counts
    total_recipients: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delivered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    read_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reply_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    order_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    order_revenue: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"), server_default="0")

    status: Mapped[str] = mapped_column(String(20), nullable=False, default=BroadcastStatus.DRAFT)

    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    recipients: Mapped[list["BroadcastRecipient"]] = relationship(back_populates="broadcast", lazy="selectin")


# ── Broadcast Recipient ──────────────────────────────────────────────────────


class RecipientStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    REPLIED = "replied"
    OPTED_OUT = "opted_out"
    SKIPPED = "skipped"  # 7-day cap or opted out


class BroadcastRecipient(BaseModel):
    """
    One row per recipient per broadcast. Tracks delivery status.
    """
    __tablename__ = "broadcast_recipients"
    __table_args__ = (
        Index("ix_broadcast_recipients_broadcast", "broadcast_id"),
        Index("ix_broadcast_recipients_customer", "customer_phone"),
    )

    broadcast_id: Mapped[str] = mapped_column(String(36), ForeignKey("broadcasts.id"), nullable=False)
    customer_phone: Mapped[str] = mapped_column(String(40), nullable=False)
    customer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default=RecipientStatus.PENDING)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    order_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # linked order if they ordered
    skip_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)

    broadcast: Mapped["Broadcast"] = relationship(back_populates="recipients")
