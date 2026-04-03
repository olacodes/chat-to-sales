from datetime import datetime

from pydantic import BaseModel

from app.modules.conversation.models import ConversationStatus, MessageSender


class MessageCreate(BaseModel):
    sender: MessageSender
    content: str
    external_id: str | None = None


class MessageOut(BaseModel):
    id: str
    sender: str
    content: str
    external_id: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationCreate(BaseModel):
    phone_number: str
    channel: str
    tenant_id: str


class ConversationOut(BaseModel):
    id: str
    tenant_id: str
    phone_number: str
    channel: str
    customer_id: str | None
    status: ConversationStatus
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut] = []

    model_config = {"from_attributes": True}
