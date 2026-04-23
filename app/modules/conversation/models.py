from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models.base import BaseModel, TenantModel

if TYPE_CHECKING:
    from app.core.models.user import User


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class MessageSender(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class Conversation(TenantModel):
    __tablename__ = "conversations"
    __table_args__ = (
        # Composite index speeds up get_or_create_conversation lookups
        Index(
            "ix_conversations_tenant_identifier_channel",
            "tenant_id",
            "customer_identifier",
            "channel",
        ),
        # Covers the list endpoint: WHERE tenant_id = ? ORDER BY updated_at DESC
        Index("ix_conversations_tenant_updated", "tenant_id", "updated_at"),
    )

    # Channel this conversation originated from (whatsapp / sms / web)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    # Nullable until customer record is created from the inbound sender
    customer_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    # Canonical sender identity: E.164 phone number or web-session ID
    customer_identifier: Mapped[str] = mapped_column(String(40), nullable=False)
    # Optional human-readable name for the customer
    customer_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ConversationStatus.ACTIVE
    )
    # Nullable FK to the staff member currently handling this conversation.
    # SET NULL on delete so removing a user never orphans conversations.
    assigned_to_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Nullable: set to a future datetime to hide this conversation until then.
    # When snoozed_until <= NOW() the conversation resurfaces at the top of the list.
    snoozed_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="conversation", lazy="selectin"
    )
    assigned_to: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[assigned_to_user_id],
        lazy="selectin",
    )
    scheduled_messages: Mapped[list["ScheduledMessage"]] = relationship(
        "ScheduledMessage", back_populates="conversation", lazy="noload"
    )


class Message(TenantModel):
    __tablename__ = "messages"
    __table_args__ = (
        # Idempotency: one external_id per conversation.
        # PostgreSQL treats NULLs as distinct, so rows with external_id=NULL
        # are never deduplicated — only rows with a real ID are.
        UniqueConstraint(
            "conversation_id",
            "external_id",
            name="uq_messages_conversation_external_id",
        ),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # "user" for inbound, "assistant" for AI replies, "system" for internal
    sender_role: Mapped[str] = mapped_column(String(20), nullable=False)
    # Customer identity — populated for user messages; NULL for assistant/system
    sender_identifier: Mapped[str | None] = mapped_column(String(40), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Channel-assigned message ID used for idempotency (e.g. WhatsApp wamid)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="messages"
    )
    reactions: Mapped[list["MessageReaction"]] = relationship(
        "MessageReaction",
        back_populates="message",
        lazy="selectin",
        cascade="all, delete-orphan",
    )


class MessageReaction(BaseModel):
    """One emoji reaction per user per message (unique on message_id + user_id)."""

    __tablename__ = "message_reactions"
    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "user_id",
            name="uq_reactions_message_user",
        ),
        Index("ix_reactions_message_id", "message_id"),
    )

    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # user_id is the staff member who reacted
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # Single emoji character (stored as-is, e.g. "👍")
    emoji: Mapped[str] = mapped_column(String(10), nullable=False)

    message: Mapped["Message"] = relationship("Message", back_populates="reactions")


class ScheduledMessage(TenantModel):
    """A message queued for future delivery to a conversation."""

    __tablename__ = "scheduled_messages"
    __table_args__ = (
        Index("ix_scheduled_messages_status_scheduled_for", "status", "scheduled_for"),
        Index("ix_scheduled_messages_conversation_id", "conversation_id"),
    )

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # "pending" → "sent" | "cancelled"
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")

    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="scheduled_messages"
    )
