"""
app/modules/notifications/models.py

Notification — a persisted record of every outbound message sent (or attempted)
to a customer.

Why persist notifications?
--------------------------
- Idempotency: the `event_id` unique constraint prevents a retry of the same
  Redis event from sending a duplicate message.
- Auditability: we can query which customers received what message and when.
- Debugging: FAILED rows pinpoint delivery failures without log scraping.
"""

from enum import StrEnum

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.base import TenantModel


class NotificationStatus(StrEnum):
    PENDING = "pending"  # created, not yet sent
    SENT = "sent"  # successfully dispatched
    FAILED = "failed"  # dispatch attempt failed


class Notification(TenantModel):
    """One outbound message sent to a customer."""

    __tablename__ = "notifications"
    __table_args__ = (
        # Fast lookup to enforce idempotency on event_id
        Index("ix_notifications_event_id", "event_id", unique=True),
        # Lookup all notifications for an order
        Index("ix_notifications_order_id", "order_id"),
    )

    # Idempotency key — set to the triggering Event.event_id so the same
    # event can never produce more than one notification row.
    event_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        comment="Triggering event UUID or compound key — unique constraint prevents duplicates",
    )

    # Where the message was sent
    recipient: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        comment="E.164 phone number or channel-specific address",
    )
    channel: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="whatsapp",
        comment="Delivery channel: whatsapp | sms | email",
    )

    # What was sent
    message_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="The rendered message body sent to the customer",
    )

    # Delivery outcome
    status: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default=NotificationStatus.PENDING,
        index=True,
    )

    # Optional context — useful for audit queries like "what did we send for order X?"
    order_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        comment="FK-like reference to orders.id (no hard FK for flexibility)",
    )
