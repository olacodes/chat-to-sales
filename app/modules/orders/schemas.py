from datetime import datetime
from decimal import Decimal
from functools import reduce

from pydantic import BaseModel, computed_field, field_validator

from app.modules.orders.models import OrderState


class OrderItemCreate(BaseModel):
    product_name: str
    quantity: int
    unit_price: Decimal

    @field_validator("quantity")
    @classmethod
    def positive_quantity(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("quantity must be greater than zero")
        return v


class OrderItemOut(BaseModel):
    id: str
    product_name: str
    quantity: int
    unit_price: Decimal

    model_config = {"from_attributes": True}


class OrderCreate(BaseModel):
    tenant_id: str
    conversation_id: str
    customer_id: str | None = None
    items: list[OrderItemCreate] = []
    currency: str = "NGN"


class OrderItemsAdd(BaseModel):
    """Request body for POST /orders/{id}/items."""

    items: list[OrderItemCreate]


class OrderOut(BaseModel):
    id: str
    tenant_id: str
    conversation_id: str
    customer_id: str | None
    state: OrderState
    amount: Decimal | None
    currency: str
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemOut] = []

    @computed_field  # type: ignore[misc]
    @property
    def total_amount(self) -> Decimal:
        """Authoritative order total.

        Returns ``amount`` when it has been persisted on the order row.
        Falls back to summing ``unit_price * quantity`` across line items
        when the order was created without an explicit amount (e.g. via the
        event-driven path before items were attached).
        """
        if self.amount is not None:
            return self.amount
        return sum(
            (item.unit_price * item.quantity for item in self.items),
            Decimal("0"),
        )

    model_config = {"from_attributes": True}


class OrderListItem(BaseModel):
    id: str
    state: OrderState
    amount: Decimal | None
    currency: str
    created_at: datetime
    updated_at: datetime
    item_count: int


class OrderListResponse(BaseModel):
    items: list[OrderListItem]
    total: int
    limit: int
    offset: int
