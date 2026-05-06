"""
app/modules/credit_sales/models.py

CreditSale tracks orders that were fulfilled on credit (pay-later).
One CreditSale per order — uniqueness enforced at the DB level.
"""

from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.base import TenantModel


class CreditSaleStatus(StrEnum):
    ACTIVE = "active"            # outstanding — customer has not paid
    SETTLED = "settled"          # fully paid — debt cleared
    DISPUTED = "disputed"        # owner flagged as disputed
    WRITTEN_OFF = "written_off"  # owner gave up chasing


class CreditSale(TenantModel):
    __tablename__ = "credit_sales"

    __table_args__ = (
        UniqueConstraint("order_id", name="uq_credit_sales_order_id"),
        Index("ix_credit_sales_tenant_status", "tenant_id", "status"),
        Index("ix_credit_sales_conversation_id", "conversation_id"),
    )

    # ── Links ─────────────────────────────────────────────────────────────────
    # Nullable: WhatsApp DEBT command creates credit sales without an order link
    order_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=True,
    )
    conversation_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Customer info (denormalized for fast display) ─────────────────────────
    customer_name: Mapped[str] = mapped_column(String(120), nullable=False)

    # ── Debt details ──────────────────────────────────────────────────────────
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NGN")
    due_date: Mapped[str | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CreditSaleStatus.ACTIVE
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Reminder tracking ─────────────────────────────────────────────────────
    reminder_interval_days: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    max_reminders: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    reminders_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_reminded_at: Mapped[str | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
