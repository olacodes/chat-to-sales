from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, field_validator

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

    model_config = {"from_attributes": True}
