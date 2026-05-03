from decimal import Decimal
from enum import StrEnum

from sqlalchemy import ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models.base import BaseModel, TenantModel


class OrderState(StrEnum):
    INQUIRY = "inquiry"  # initial — customer expressed intent
    CONFIRMED = "confirmed"  # order details agreed, awaiting payment
    PAID = "paid"  # payment received
    COMPLETED = "completed"  # fulfilled / delivered (terminal)
    FAILED = "failed"  # cancelled / error (terminal)


class Order(TenantModel):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_tenant_state", "tenant_id", "state"),
        Index("ix_orders_conversation_state", "conversation_id", "state"),
        # Covers dashboard list: WHERE tenant_id = ? ORDER BY created_at DESC
        Index("ix_orders_tenant_created", "tenant_id", "created_at"),
        # Covers filtered list: WHERE tenant_id = ? AND state = ? ORDER BY created_at DESC
        Index("ix_orders_tenant_state_created", "tenant_id", "state", "created_at"),
    )

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # E.164 phone number of the customer who placed this order.
    # Stored here so trader-command handlers can notify the customer without
    # an extra join back through conversations.
    customer_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # E.164 phone number of the trader (store owner) who owns this order.
    # Used to migrate orders from the shared platform tenant to the trader's
    # dedicated tenant on first dashboard login.
    trader_phone: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default=OrderState.INQUIRY, index=True
    )
    # Nullable so an order can be created before the amount is known
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NGN")

    items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem", back_populates="order", lazy="selectin"
    )


class OrderItem(BaseModel):
    __tablename__ = "order_items"

    order_id: Mapped[str] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    order: Mapped["Order"] = relationship("Order", back_populates="items")
