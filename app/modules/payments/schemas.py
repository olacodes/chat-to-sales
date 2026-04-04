"""
app/modules/payments/schemas.py
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.modules.orders.models import OrderState
from app.modules.payments.models import PaymentStatus


class PaymentInitiateRequest(BaseModel):
    """Request body for POST /payments/ — initiates a checkout link."""

    order_id: str
    tenant_id: str


class PaymentOut(BaseModel):
    id: str
    tenant_id: str
    order_id: str
    reference: str
    amount: Decimal
    currency: str
    status: PaymentStatus
    provider: str
    payment_link: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PaymentListItem(BaseModel):
    id: str
    order_id: str
    reference: str
    amount: Decimal
    currency: str
    status: PaymentStatus
    provider: str
    created_at: datetime
    order_state: OrderState
    order_amount: Decimal | None


class PaymentListResponse(BaseModel):
    items: list[PaymentListItem]
    total: int
    limit: int
    offset: int


class PaystackWebhookPayload(BaseModel):
    """
    Top-level shape of a Paystack webhook POST body.

    Paystack always sends:
        { "event": "charge.success", "data": { "reference": "...", ... } }

    The router reads the raw body for signature verification and then
    parses it into this schema.
    """

    event: str
    data: dict
