from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
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

    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="conversation", lazy="selectin"
    )
    assigned_to: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[assigned_to_user_id],
        lazy="selectin",
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
