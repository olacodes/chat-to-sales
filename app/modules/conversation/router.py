from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import DBSessionDep
from app.modules.conversation.schemas import (
    ConversationCreate,
    ConversationOut,
    MessageCreate,
    MessageOut,
)
from app.modules.conversation.service import ConversationService

router = APIRouter(prefix="/conversations", tags=["Conversation"])


def _service(db: DBSessionDep) -> ConversationService:
    return ConversationService(db)


ServiceDep = Annotated[ConversationService, Depends(_service)]


@router.post("/", status_code=201)
async def start_conversation(
    body: ConversationCreate,
    svc: ServiceDep,
) -> ConversationOut:
    return await svc.get_or_create(
        body.phone_number,
        channel=body.channel,
        tenant_id=body.tenant_id,
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
