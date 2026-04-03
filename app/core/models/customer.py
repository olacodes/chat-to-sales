"""
app/core/models/customer.py

Customer — the primary contact record for a tenant.

A Customer maps 1-to-1 with a WhatsApp phone number within a tenant.
Multiple conversations, orders, and payments will reference this record.
"""

from enum import StrEnum

from sqlalchemy import Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.base import TenantModel


class CustomerStatus(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    UNSUBSCRIBED = "unsubscribed"


class Customer(TenantModel):
    """
    Represents a customer (end-user) who messages the tenant's WhatsApp number.

    Uniqueness:
        A phone number is unique per tenant — the same real person can be a
        customer of multiple tenants via different WhatsApp Business Accounts.
    """

    __tablename__ = "customers"

    __table_args__ = (
        # Enforce one record per phone number per tenant
        UniqueConstraint("tenant_id", "phone_number", name="uq_customers_tenant_phone"),
        # Compound index for the common query pattern: tenant + status
        Index("ix_customers_tenant_status", "tenant_id", "status"),
    )

    phone_number: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="E.164 formatted WhatsApp phone number, e.g. +2348012345678",
    )
    display_name: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
        comment="Name as reported by WhatsApp profile or set manually",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=CustomerStatus.ACTIVE,
        nullable=False,
        comment="Lifecycle status — controls whether messages are accepted",
    )
    language_code: Mapped[str] = mapped_column(
        String(10),
        default="en",
        nullable=False,
        comment="BCP-47 language tag for notification localisation",
    )
    metadata_json: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
        comment="Arbitrary JSON blob for tenant-specific attributes",
    )
