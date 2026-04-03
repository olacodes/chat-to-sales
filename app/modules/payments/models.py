"""
app/modules/payments/models.py

Payment entity.  One Payment record is created per checkout attempt for an
order. The `reference` field is the unique key shared with the payment
provider (Paystack) and is used for webhook deduplication.
"""

from decimal import Decimal
from enum import StrEnum

from sqlalchemy import ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.base import TenantModel


class PaymentStatus(StrEnum):
    PENDING = "pending"  # created, awaiting provider confirmation
    SUCCESS = "success"  # provider confirmed payment
    FAILED = "failed"  # provider reported failure or webhook FAILED event


class Payment(TenantModel):
    __tablename__ = "payments"
    __table_args__ = (
        # Composite index for looking up payments by order within a tenant
        Index("ix_payments_tenant_order", "tenant_id", "order_id"),
    )

    order_id: Mapped[str] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Provider-assigned unique reference — used for webhook deduplication.
    # unique=True enforces idempotency at the database level.
    reference: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NGN")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PaymentStatus.PENDING, index=True
    )
    provider: Mapped[str] = mapped_column(
        String(30), nullable=False, default="paystack"
    )
    # Checkout URL returned to the customer (mock or real Paystack link)
    payment_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
