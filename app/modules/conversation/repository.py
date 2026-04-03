"""
app/modules/conversation/repository.py

Data-access layer for Conversation and Message entities.

Design notes
------------
- Every public method is async and uses SQLAlchemy 2.0 select() style.
- Methods are keyword-argument only (after the self param) to eliminate
  positional argument ordering bugs at call sites.
- get_or_create_conversation() returns a (Conversation, bool) tuple so
  callers can distinguish first-contact from a returning sender.
- save_message() performs an application-level idempotency check before
  INSERT and returns None for duplicates instead of raising. The database
  UniqueConstraint on (conversation_id, external_id) acts as a safety net.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.conversation.models import (
    Conversation,
    ConversationStatus,
    Message,
    MessageSender,
)

logger = get_logger(__name__)


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Conversation ──────────────────────────────────────────────────────────

    async def create_conversation(
        self,
        *,
        tenant_id: str,
        channel: str,
        phone_number: str,
        customer_id: str | None = None,
    ) -> Conversation:
        """Persist a new ACTIVE conversation and flush to get a DB-assigned id."""
        conv = Conversation(
            tenant_id=tenant_id,
            channel=channel,
            phone_number=phone_number,
            customer_id=customer_id,
            status=ConversationStatus.ACTIVE,
        )
        self._session.add(conv)
        await self._session.flush()
        logger.debug(
            "Conversation created id=%s tenant=%s channel=%s",
            conv.id,
            tenant_id,
            channel,
        )
        return conv

    async def get_conversation_by_sender(
        self,
        *,
        tenant_id: str,
        phone_number: str,
        channel: str,
    ) -> Conversation | None:
        """
        Return the most recent ACTIVE conversation for a sender on a channel,
        or None when no active conversation exists.
        """
        result = await self._session.execute(
            select(Conversation)
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.phone_number == phone_number,
                Conversation.channel == channel,
                Conversation.status == ConversationStatus.ACTIVE,
            )
            .order_by(Conversation.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_or_create_conversation(
        self,
        *,
        tenant_id: str,
        phone_number: str,
        channel: str,
        customer_id: str | None = None,
    ) -> tuple[Conversation, bool]:
        """
        Return (conversation, was_created).

        If an active conversation already exists for (tenant_id, phone_number,
        channel) it is returned immediately. Otherwise a new one is created,
        flushed, and returned with was_created=True.
        """
        conv = await self.get_conversation_by_sender(
            tenant_id=tenant_id,
            phone_number=phone_number,
            channel=channel,
        )
        if conv is not None:
            return conv, False

        conv = await self.create_conversation(
            tenant_id=tenant_id,
            channel=channel,
            phone_number=phone_number,
            customer_id=customer_id,
        )
        return conv, True

    async def get_conversation_by_id(
        self,
        *,
        conversation_id: str,
        tenant_id: str | None = None,
    ) -> Conversation | None:
        """
        Fetch a conversation by primary key.

        When tenant_id is supplied the query is tenant-scoped, preventing
        cross-tenant data leakage. Pass None only for internal/admin paths
        where tenant context is unavailable.
        """
        stmt = select(Conversation).where(Conversation.id == conversation_id)
        if tenant_id:
            stmt = stmt.where(Conversation.tenant_id == tenant_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    # ── Message ───────────────────────────────────────────────────────────────

    async def get_message_by_external_id(
        self,
        *,
        conversation_id: str,
        external_id: str,
    ) -> Message | None:
        """Look up a previously stored message by its channel-assigned ID."""
        result = await self._session.execute(
            select(Message).where(
                Message.conversation_id == conversation_id,
                Message.external_id == external_id,
            )
        )
        return result.scalar_one_or_none()

    async def save_message(
        self,
        *,
        conversation_id: str,
        tenant_id: str,
        sender: str,
        content: str,
        external_id: str | None = None,
    ) -> Message | None:
        """
        Persist a message and return it.

        Returns **None** when a message with the same external_id already
        exists for this conversation — providing application-level idempotency
        for duplicate webhook deliveries. The database UniqueConstraint on
        (conversation_id, external_id) acts as a secondary safety net.
        """
        if external_id is not None:
            existing = await self.get_message_by_external_id(
                conversation_id=conversation_id,
                external_id=external_id,
            )
            if existing is not None:
                logger.info(
                    "Duplicate message dropped conversation=%s external_id=%s",
                    conversation_id,
                    external_id,
                )
                return None

        msg = Message(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            sender=sender,
            content=content,
            external_id=external_id,
        )
        self._session.add(msg)
        await self._session.flush()
        logger.debug(
            "Message saved id=%s conversation=%s sender=%s",
            msg.id,
            conversation_id,
            sender,
        )
        return msg
