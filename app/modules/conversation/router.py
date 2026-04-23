from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import DBSessionDep
from app.modules.conversation.schemas import (
    AssignConversationRequest,
    AssignmentOut,
    ConversationCreate,
    ConversationListItem,
    ConversationListResponse,
    ConversationOut,
    MessageCreate,
    MessageListResponse,
    MessageOut,
    ReactionCreate,
    ScheduledMessageListResponse,
    ScheduledMessageOut,
    ScheduleMessageRequest,
)
from app.modules.conversation.service import ConversationService

router = APIRouter(prefix="/conversations", tags=["Conversation"])


def _service(db: DBSessionDep) -> ConversationService:
    return ConversationService(db)


ServiceDep = Annotated[ConversationService, Depends(_service)]


@router.get("")
async def list_conversations(
    tenant_id: str,
    svc: ServiceDep,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> ConversationListResponse:
    return await svc.list_conversations(
        tenant_id=tenant_id,
        limit=limit,
        cursor=cursor,
    )


@router.post("", status_code=201)
async def start_conversation(
    body: ConversationCreate,
    svc: ServiceDep,
) -> ConversationOut:
    return await svc.get_or_create(
        body.customer_identifier,
        channel=body.channel,
        tenant_id=body.tenant_id,
        customer_name=body.customer_name,
    )


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    svc: ServiceDep,
) -> ConversationOut:
    return await svc.get_by_id(conversation_id)


@router.post("/{conversation_id}/messages", status_code=201)
async def add_message(
    conversation_id: str,
    body: MessageCreate,
    svc: ServiceDep,
) -> MessageOut:
    return await svc.add_message(conversation_id, body)


@router.patch("/{conversation_id}/assign")
async def assign_conversation(
    conversation_id: str,
    tenant_id: str,
    body: AssignConversationRequest,
    svc: ServiceDep,
) -> AssignmentOut:
    return await svc.assign_conversation(
        conversation_id,
        tenant_id=tenant_id,
        user_id=body.user_id,
        assigned_by_user_id=body.assigned_by_user_id,
    )


@router.post("/{conversation_id}/messages/{message_id}/reactions")
async def react_to_message(
    conversation_id: str,
    message_id: str,
    body: ReactionCreate,
    svc: ServiceDep,
) -> MessageOut:
    return await svc.react_to_message(conversation_id, message_id, body)


@router.get("/{conversation_id}/messages")
async def list_messages(
    conversation_id: str,
    tenant_id: str,
    svc: ServiceDep,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
) -> MessageListResponse:
    return await svc.list_messages(
        conversation_id,
        tenant_id=tenant_id,
        limit=limit,
        cursor=cursor,
    )


# ── Scheduled messages ────────────────────────────────────────────────────────


@router.post(
    "/{conversation_id}/scheduled-messages",
    status_code=status.HTTP_201_CREATED,
)
async def create_scheduled_message(
    conversation_id: str,
    tenant_id: str,
    body: ScheduleMessageRequest,
    svc: ServiceDep,
) -> ScheduledMessageOut:
    """Schedule a message to be sent at a future time."""
    return await svc.create_scheduled_message(
        conversation_id,
        tenant_id=tenant_id,
        data=body,
    )


@router.get("/{conversation_id}/scheduled-messages")
async def list_scheduled_messages(
    conversation_id: str,
    tenant_id: str,
    svc: ServiceDep,
) -> ScheduledMessageListResponse:
    """List all scheduled messages for a conversation."""
    return await svc.list_scheduled_messages(
        conversation_id,
        tenant_id=tenant_id,
    )


@router.delete(
    "/{conversation_id}/scheduled-messages/{scheduled_message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_scheduled_message(
    conversation_id: str,
    scheduled_message_id: str,
    tenant_id: str,
    svc: ServiceDep,
) -> None:
    """Cancel (delete) a pending scheduled message."""
    await svc.cancel_scheduled_message(
        conversation_id,
        scheduled_message_id,
        tenant_id=tenant_id,
    )
