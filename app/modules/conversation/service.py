"""
app/modules/conversation/service.py

ConversationService orchestrates the conversation lifecycle.

Responsibilities
----------------
- handle_inbound()   — event-driven path; called from the event handler
- get_or_create()    — HTTP API convenience wrapper
- get_by_id()        — read path for the REST API
- add_message()      — HTTP API path for adding messages to a conversation
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.modules.conversation.models import Conversation, Message, MessageSender
from app.modules.conversation.repository import ConversationRepository
from app.modules.conversation.schemas import MessageCreate

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
            phone_number=sender_id,
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
            sender=MessageSender.USER,
            content=content,
            external_id=external_id,
        )
        # NOTE: commit is intentionally omitted here.
        # The caller (handler or HTTP request) owns the transaction boundary.
        return conv, msg

    # ── HTTP API methods ──────────────────────────────────────────────────────

    async def get_or_create(
        self,
        phone_number: str,
        *,
        channel: str,
        tenant_id: str,
    ) -> Conversation:
        """Used by the REST API to start or resume a conversation."""
        conv, _ = await self._repo.get_or_create_conversation(
            tenant_id=tenant_id,
            phone_number=phone_number,
            channel=channel,
        )
        await self._db.commit()
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
        msg = await self._repo.save_message(
            conversation_id=conv.id,
            tenant_id=conv.tenant_id,
            sender=data.sender,
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
