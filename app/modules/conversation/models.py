from enum import StrEnum

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.models.base import BaseModel, TenantModel


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
            "ix_conversations_tenant_phone_channel",
            "tenant_id",
            "phone_number",
            "channel",
        ),
    )

    # Channel this conversation originated from (whatsapp / sms / web)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    # Nullable until customer record is created from the inbound sender
    customer_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    # Sender identifier: E.164 phone number or web-session ID
    phone_number: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ConversationStatus.ACTIVE
    )

    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="conversation", lazy="selectin"
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
    sender: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Channel-assigned message ID used for idempotency (e.g. WhatsApp wamid)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="messages"
    )
