"""
app/modules/onboarding/models.py

Trader — the WhatsApp-registered business profile.

A Trader is distinct from the dashboard User/Tenant system.
They sign up entirely through WhatsApp and are identified by phone number.
"""

from enum import StrEnum

from sqlalchemy import Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.base import BaseModel, TenantMixin


class OnboardingStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"


class TraderTier(StrEnum):
    OFE = "ofe"
    OJA = "oja"
    ALATISE = "alatise"


class BusinessCategory(StrEnum):
    PROVISIONS = "provisions"
    FABRIC = "fabric"
    FOOD = "food"
    ELECTRONICS = "electronics"
    COSMETICS = "cosmetics"
    BUILDING = "building"
    OTHER = "other"


class Trader(BaseModel):
    __tablename__ = "traders"
    __table_args__ = (
        UniqueConstraint("phone_number", name="uq_traders_phone_number"),
        UniqueConstraint("store_slug", name="uq_traders_store_slug"),
        Index("ix_traders_phone_number", "phone_number"),
        Index("ix_traders_store_slug", "store_slug"),
        Index("ix_traders_tenant_id", "tenant_id"),
    )

    # The ChatToSales tenant this trader belongs to (set during onboarding).
    # Nullable for backwards compatibility with traders created before this field.
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # WhatsApp identity — E.164 phone number, e.g. "2348012345678"
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)

    business_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # One of the BusinessCategory values, or a free-text description for "other"
    business_category: Mapped[str | None] = mapped_column(String(60), nullable=True)

    # URL slug, e.g. "mama-caro-provisions" → chattosales.com/store/mama-caro-provisions
    store_slug: Mapped[str | None] = mapped_column(String(120), nullable=True)

    onboarding_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=OnboardingStatus.IN_PROGRESS
    )

    tier: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TraderTier.OFE
    )

    # Items collected during onboarding Q&A — JSON text, consumed by Feature 3
    # Format: '{"Indomie Carton": 8500, "Rice 50kg": 63000}'
    onboarding_catalogue: Mapped[str | None] = mapped_column(Text, nullable=True)
