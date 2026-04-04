from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import DBSessionDep
from app.modules.conversation.schemas import (
    ConversationCreate,
    ConversationListResponse,
    ConversationOut,
    MessageCreate,
    MessageListResponse,
    MessageOut,
)
from app.modules.conversation.service import ConversationService

router = APIRouter(prefix="/conversations", tags=["Conversation"])


def _service(db: DBSessionDep) -> ConversationService:
    return ConversationService(db)


ServiceDep = Annotated[ConversationService, Depends(_service)]


@router.get("/")
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


@router.post("/", status_code=201)
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
