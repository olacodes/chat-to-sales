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

from datetime import datetime, timezone

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.core.logging import get_logger
from app.modules.conversation.models import (
    Conversation,
    ConversationStatus,
    Message,
    MessageReaction,
    MessageSender,
    ScheduledMessage,
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
        customer_identifier: str,
        customer_name: str | None = None,
        customer_id: str | None = None,
    ) -> Conversation:
        """Persist a new ACTIVE conversation and flush to get a DB-assigned id."""
        conv = Conversation(
            tenant_id=tenant_id,
            channel=channel,
            customer_identifier=customer_identifier,
            customer_name=customer_name,
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
        customer_identifier: str,
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
                Conversation.customer_identifier == customer_identifier,
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
        customer_identifier: str,
        channel: str,
        customer_name: str | None = None,
        customer_id: str | None = None,
    ) -> tuple[Conversation, bool]:
        """
        Return (conversation, was_created).

        If an active conversation already exists for
        (tenant_id, customer_identifier, channel) it is returned immediately.
        Otherwise a new one is created, flushed, and returned with was_created=True.
        """
        conv = await self.get_conversation_by_sender(
            tenant_id=tenant_id,
            customer_identifier=customer_identifier,
            channel=channel,
        )
        if conv is not None:
            return conv, False

        conv = await self.create_conversation(
            tenant_id=tenant_id,
            channel=channel,
            customer_identifier=customer_identifier,
            customer_name=customer_name,
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
        sender_role: str,
        content: str,
        external_id: str | None = None,
        sender_identifier: str | None = None,
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
            sender_role=sender_role,
            sender_identifier=sender_identifier,
            content=content,
            external_id=external_id,
        )
        self._session.add(msg)
        await self._session.flush()
        logger.debug(
            "Message saved id=%s conversation=%s sender_role=%s",
            msg.id,
            conversation_id,
            sender_role,
        )
        return msg

    async def assign_conversation(
        self,
        *,
        conversation_id: str,
        tenant_id: str,
        user_id: str | None,
    ) -> Conversation | None:
        """
        Set or clear the assigned_to_user_id on a conversation.

        Returns the updated Conversation, or None if not found.
        The caller owns the transaction boundary (commit/rollback).
        """
        conv = await self.get_conversation_by_id(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
        )
        if conv is None:
            return None
        conv.assigned_to_user_id = user_id
        await self._session.flush()
        return conv

    # ── Reactions ─────────────────────────────────────────────────────────────

    async def get_message_by_id(
        self,
        *,
        message_id: str,
        conversation_id: str,
    ) -> Message | None:
        """Return a message by primary key, scoped to its conversation."""
        result = await self._session.execute(
            select(Message).where(
                Message.id == message_id,
                Message.conversation_id == conversation_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_reaction(
        self,
        *,
        message_id: str,
        user_id: str,
    ) -> MessageReaction | None:
        """Return the existing reaction from a user on a message, or None."""
        result = await self._session.execute(
            select(MessageReaction).where(
                MessageReaction.message_id == message_id,
                MessageReaction.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert_reaction(
        self,
        *,
        message_id: str,
        tenant_id: str,
        user_id: str,
        emoji: str,
    ) -> MessageReaction:
        """Create or replace the user's reaction on a message."""
        existing = await self.get_reaction(message_id=message_id, user_id=user_id)
        if existing is not None:
            existing.emoji = emoji
            await self._session.flush()
            return existing
        reaction = MessageReaction(
            message_id=message_id,
            tenant_id=tenant_id,
            user_id=user_id,
            emoji=emoji,
        )
        self._session.add(reaction)
        await self._session.flush()
        return reaction

    async def delete_reaction(
        self,
        *,
        message_id: str,
        user_id: str,
    ) -> bool:
        """Delete a user's reaction. Returns True if deleted, False if not found."""
        existing = await self.get_reaction(message_id=message_id, user_id=user_id)
        if existing is None:
            return False
        await self._session.delete(existing)
        await self._session.flush()
        return True

    # ── List queries ──────────────────────────────────────────────────────────

    async def list_conversations(
        self,
        *,
        tenant_id: str,
        limit: int,
        cursor_dt: datetime | None = None,
        cursor_id: str | None = None,
    ) -> tuple[list[Conversation], dict[str, "Message"]]:
        """
        Return a page of conversations with snooze-aware ordering.

        Order:
        1. Active conversations (snoozed_until IS NULL or <= NOW()) — updated_at DESC
        2. Snoozed conversations (snoozed_until > NOW()) — snoozed_until ASC (resurfaces soonest first)

        Uses noload() to skip the selectin relationship load — we fetch the
        last message separately in a single batched query.

        Returns (conversations, last_message_by_conv_id).
        """
        now = datetime.now(timezone.utc)

        # 0 = active/due (shown at top), 1 = actively snoozed (shown at bottom)
        snooze_group = case(
            (
                and_(
                    Conversation.snoozed_until.is_not(None),
                    Conversation.snoozed_until > now,
                ),
                1,
            ),
            else_=0,
        )

        stmt = (
            select(Conversation)
            .options(noload(Conversation.messages))
            .where(Conversation.tenant_id == tenant_id)
            .order_by(
                snooze_group,
                Conversation.updated_at.desc(),
                Conversation.id.desc(),
            )
            .limit(limit)
        )
        if cursor_dt is not None and cursor_id is not None:
            stmt = stmt.where(
                or_(
                    Conversation.updated_at < cursor_dt,
                    and_(
                        Conversation.updated_at == cursor_dt,
                        Conversation.id < cursor_id,
                    ),
                )
            )
        result = await self._session.execute(stmt)
        convs = list(result.scalars().all())

        last_msgs: dict[str, Message] = {}
        if convs:
            conv_ids = [c.id for c in convs]
            # DISTINCT ON (conversation_id) with ORDER BY created_at DESC gives
            # the most recent message per conversation in one round-trip.
            msg_stmt = (
                select(Message)
                .where(Message.conversation_id.in_(conv_ids))
                .distinct(Message.conversation_id)
                .order_by(Message.conversation_id, Message.created_at.desc())
            )
            msg_result = await self._session.execute(msg_stmt)
            for msg in msg_result.scalars().all():
                last_msgs[msg.conversation_id] = msg

        return convs, last_msgs

    # ── Snooze ────────────────────────────────────────────────────────────────

    async def snooze_conversation(
        self,
        *,
        conversation_id: str,
        tenant_id: str,
        snoozed_until: datetime | None,
    ) -> Conversation | None:
        """
        Set or clear the snoozed_until timestamp on a conversation.

        Returns the updated Conversation, or None if not found.
        The caller owns the transaction boundary.
        """
        conv = await self.get_conversation_by_id(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
        )
        if conv is None:
            return None
        conv.snoozed_until = snoozed_until
        await self._session.flush()
        return conv

    # ── Scheduled messages ────────────────────────────────────────────────────

    async def create_scheduled_message(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        content: str,
        scheduled_for: datetime,
    ) -> ScheduledMessage:
        """Persist a new pending scheduled message."""
        sm = ScheduledMessage(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            content=content,
            scheduled_for=scheduled_for,
            status="pending",
        )
        self._session.add(sm)
        await self._session.flush()
        logger.debug(
            "ScheduledMessage created id=%s conversation=%s scheduled_for=%s",
            sm.id,
            conversation_id,
            scheduled_for,
        )
        return sm

    async def list_scheduled_messages(
        self,
        *,
        conversation_id: str,
        tenant_id: str,
    ) -> list[ScheduledMessage]:
        """Return all scheduled messages for a conversation, ordered by scheduled_for ASC."""
        result = await self._session.execute(
            select(ScheduledMessage)
            .where(
                ScheduledMessage.conversation_id == conversation_id,
                ScheduledMessage.tenant_id == tenant_id,
            )
            .order_by(ScheduledMessage.scheduled_for.asc())
        )
        return list(result.scalars().all())

    async def get_scheduled_message_by_id(
        self,
        *,
        scheduled_message_id: str,
        conversation_id: str,
        tenant_id: str,
    ) -> ScheduledMessage | None:
        """Fetch a single scheduled message scoped to its conversation and tenant."""
        result = await self._session.execute(
            select(ScheduledMessage).where(
                ScheduledMessage.id == scheduled_message_id,
                ScheduledMessage.conversation_id == conversation_id,
                ScheduledMessage.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def cancel_scheduled_message(
        self,
        *,
        scheduled_message_id: str,
        conversation_id: str,
        tenant_id: str,
    ) -> bool:
        """
        Delete a pending scheduled message.

        Returns True if deleted, False if not found or already sent/cancelled.
        """
        sm = await self.get_scheduled_message_by_id(
            scheduled_message_id=scheduled_message_id,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
        )
        if sm is None or sm.status != "pending":
            return False
        await self._session.delete(sm)
        await self._session.flush()
        return True

    async def get_pending_scheduled_messages(
        self,
        *,
        now: datetime,
    ) -> list[ScheduledMessage]:
        """Return all pending scheduled messages whose scheduled_for <= now."""
        result = await self._session.execute(
            select(ScheduledMessage).where(
                ScheduledMessage.status == "pending",
                ScheduledMessage.scheduled_for <= now,
            )
        )
        return list(result.scalars().all())

    async def list_messages(
        self,
        *,
        conversation_id: str,
        limit: int,
        cursor_dt: datetime | None = None,
        cursor_id: str | None = None,
    ) -> list[Message]:
        """
        Return a page of messages for a conversation ordered by created_at ASC.

        The existing ix_messages_conversation_created index covers this query.
        """
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
            .limit(limit)
        )
        if cursor_dt is not None and cursor_id is not None:
            stmt = stmt.where(
                or_(
                    Message.created_at > cursor_dt,
                    and_(
                        Message.created_at == cursor_dt,
                        Message.id > cursor_id,
                    ),
                )
            )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
