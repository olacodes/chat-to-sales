"""
app/modules/credit_sales/schemas.py
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.modules.credit_sales.models import CreditSaleStatus


class CreditSaleCreate(BaseModel):
    order_id: str
    conversation_id: str | None = None
    customer_name: str
    amount: Decimal = Field(..., gt=0)
    currency: str = "NGN"
    due_date: date | None = None
    reminder_interval_days: int = Field(default=3, ge=1, le=30)
    max_reminders: int = Field(default=5, ge=1, le=20)
    notes: str | None = None


class CreditSaleOut(BaseModel):
    id: str
    tenant_id: str
    order_id: str
    conversation_id: str | None
    customer_name: str
    amount: Decimal
    currency: str
    due_date: date | None
    status: CreditSaleStatus
    reminder_interval_days: int
    max_reminders: int
    reminders_sent: int
    last_reminded_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CreditSaleListResponse(BaseModel):
    items: list[CreditSaleOut]
    total: int


class ReminderOut(BaseModel):
    credit_sale_id: str
    reminders_sent: int
    message_sent: str
