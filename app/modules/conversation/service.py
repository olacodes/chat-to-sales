"""
app/modules/conversation/service.py

ConversationService orchestrates the conversation lifecycle.

Responsibilities
----------------
- handle_inbound()       — event-driven path; called from the event handler
- get_or_create()        — HTTP API convenience wrapper
- get_by_id()            — read path for the REST API
- add_message()          — HTTP API path for adding messages to a conversation
- list_conversations()   — paginated conversation list for a tenant
- list_messages()        — paginated message list for a conversation
"""

import base64
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.modules.conversation.models import Conversation, Message, MessageSender
from app.modules.conversation.repository import ConversationRepository
from app.modules.conversation.schemas import (
    ConversationListItem,
    ConversationListResponse,
    LastMessage,
    MessageCreate,
    MessageListResponse,
)

logger = get_logger(__name__)


class ConversationService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._repo = ConversationRepository(db)

    # ── Event-driven entry point ──────────────────────────────────────────────

    async def handle_inbound(
        self,
        *,
        tenant_id: str,
        channel: str,
        sender_id: str,
        content: str,
        external_id: str | None = None,
        customer_id: str | None = None,
    ) -> tuple[Conversation, Message | None]:
        """
        Persist an inbound message, creating the conversation if needed.

        Returns (conversation, message).  message is None when external_id was
        already seen for this conversation (idempotency guard fired).

        The caller is responsible for committing or rolling back the session.
        """
        conv, created = await self._repo.get_or_create_conversation(
            tenant_id=tenant_id,
            customer_identifier=sender_id,
            channel=channel,
            customer_id=customer_id,
        )

        if created:
            logger.info(
                "New conversation id=%s tenant=%s channel=%s sender=%s",
                conv.id,
                tenant_id,
                channel,
                sender_id,
            )

        msg = await self._repo.save_message(
            conversation_id=conv.id,
            tenant_id=tenant_id,
            sender_role=MessageSender.USER,
            sender_identifier=sender_id,
            content=content,
            external_id=external_id,
        )
        # NOTE: commit is intentionally omitted here.
        # The caller (handler or HTTP request) owns the transaction boundary.
        return conv, msg

    # ── HTTP API methods ──────────────────────────────────────────────────────

    async def get_or_create(
        self,
        customer_identifier: str,
        *,
        channel: str,
        tenant_id: str,
        customer_name: str | None = None,
    ) -> Conversation:
        """Used by the REST API to start or resume a conversation."""
        conv, was_created = await self._repo.get_or_create_conversation(
            tenant_id=tenant_id,
            customer_identifier=customer_identifier,
            channel=channel,
            customer_name=customer_name,
        )
        await self._db.commit()
        if was_created:
            # Re-query so selectin-loaded relationships (messages) are available
            # for response serialisation.  populate_existing=True forces a fresh
            # load even though the object is already in the identity map.
            result = await self._db.execute(
                select(Conversation)
                .where(Conversation.id == conv.id)
                .execution_options(populate_existing=True)
            )
            conv = result.scalar_one()
        return conv

    async def get_by_id(
        self,
        conversation_id: str,
        *,
        tenant_id: str | None = None,
    ) -> Conversation:
        """
        Return a conversation by id, or raise NotFoundError.

        Supply tenant_id whenever the caller has a tenant context to prevent
        cross-tenant data leakage.  The parameter is intentionally optional
        only for internal/admin paths that operate without a tenant context.
        """
        conv = await self._repo.get_conversation_by_id(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
        )
        if conv is None:
            raise NotFoundError("Conversation", conversation_id)
        return conv

    async def add_message(
        self,
        conversation_id: str,
        data: MessageCreate,
    ) -> Message:
        """Add a message to an existing conversation (REST API path)."""
        conv = await self.get_by_id(conversation_id)
        # Derive sender identity from the conversation — callers never supply it.
        # user    → sender_identifier = conversation's customer_identifier
        # others  → sender_identifier = None (assistant/system have no customer identity)
        if data.sender_role == MessageSender.USER:
            sender_identifier: str | None = conv.customer_identifier
        else:
            sender_identifier = None
        msg = await self._repo.save_message(
            conversation_id=conv.id,
            tenant_id=conv.tenant_id,
            sender_role=data.sender_role,
            sender_identifier=sender_identifier,
            content=data.content,
            external_id=data.external_id,
        )
        if msg is None:
            # Idempotency: return the pre-existing message
            existing = await self._repo.get_message_by_external_id(
                conversation_id=conversation_id,
                external_id=data.external_id,  # type: ignore[arg-type]
            )
            return existing  # type: ignore[return-value]
        await self._db.commit()
        return msg

    # ── List methods ──────────────────────────────────────────────────────────

    async def list_conversations(
        self,
        *,
        tenant_id: str,
        limit: int = 20,
        cursor: str | None = None,
    ) -> ConversationListResponse:
        """Return a cursor-paginated list of conversations for a tenant."""
        cursor_dt, cursor_id = _decode_cursor(cursor) if cursor else (None, None)

        convs, last_msgs = await self._repo.list_conversations(
            tenant_id=tenant_id,
            limit=limit + 1,
            cursor_dt=cursor_dt,
            cursor_id=cursor_id,
        )

        has_more = len(convs) > limit
        if has_more:
            convs = convs[:limit]

        next_cursor: str | None = None
        if has_more and convs:
            last = convs[-1]
            next_cursor = _encode_cursor(last.updated_at.isoformat(), last.id)

        items = []
        for conv in convs:
            msg = last_msgs.get(conv.id)
            last_message = (
                LastMessage(content=msg.content, timestamp=msg.created_at)
                if msg
                else None
            )
            items.append(
                ConversationListItem(
                    id=conv.id,
                    customer_identifier=conv.customer_identifier,
                    customer_name=conv.customer_name,
                    status=conv.status,
                    last_message=last_message,
                    updated_at=conv.updated_at,
                )
            )

        return ConversationListResponse(items=items, next_cursor=next_cursor)

    async def list_messages(
        self,
        conversation_id: str,
        *,
        tenant_id: str,
        limit: int = 50,
        cursor: str | None = None,
    ) -> MessageListResponse:
        """Return a cursor-paginated list of messages for a conversation."""
        # Tenant-scoped lookup guards cross-tenant access
        await self.get_by_id(conversation_id, tenant_id=tenant_id)

        cursor_dt, cursor_id = _decode_cursor(cursor) if cursor else (None, None)

        msgs = await self._repo.list_messages(
            conversation_id=conversation_id,
            limit=limit + 1,
            cursor_dt=cursor_dt,
            cursor_id=cursor_id,
        )

        has_more = len(msgs) > limit
        if has_more:
            msgs = msgs[:limit]

        next_cursor = None
        if has_more and msgs:
            last = msgs[-1]
            next_cursor = _encode_cursor(last.created_at.isoformat(), last.id)

        return MessageListResponse(items=msgs, next_cursor=next_cursor)


# ── Cursor helpers ────────────────────────────────────────────────────────────


def _encode_cursor(ts: str, row_id: str) -> str:
    """Base64-encode a (timestamp_iso, id) pair into an opaque cursor string."""
    return base64.urlsafe_b64encode(json.dumps([ts, row_id]).encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    """Decode a cursor produced by _encode_cursor."""
    ts, row_id = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    return datetime.fromisoformat(ts), row_id
