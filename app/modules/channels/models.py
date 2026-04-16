"""
app/modules/channels/models.py

ORM model for the tenant_channels table.

Stores one row per (tenant, channel) pair. The access_token is stored
encrypted — never in plaintext. The unique constraint on (tenant_id, channel)
makes upserts safe and idempotent.
"""

from enum import StrEnum

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.base import TenantModel


class ChannelName(StrEnum):
    WHATSAPP = "whatsapp"
    # SMS = "sms"     ← extend here when ready
    # INSTAGRAM = "instagram"


class TenantChannel(TenantModel):
    __tablename__ = "tenant_channels"
    __table_args__ = (
        # One active channel config per tenant per channel type.
        # Repeated connect calls UPDATE the existing row (idempotent).
        UniqueConstraint(
            "tenant_id", "channel", name="uq_tenant_channels_tenant_channel"
        ),
    )

    channel: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="Channel type: whatsapp | sms | instagram",
    )
    phone_number_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Meta phone_number_id (or equivalent channel identifier)",
    )
    # Token is stored encrypted (Fernet). NEVER store plaintext here.
    encrypted_access_token: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Fernet-encrypted access token",
    )
    # Tracks last webhook registration attempt for observability.
    webhook_registered: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        comment="True when the webhook was successfully registered with Meta",
    )
