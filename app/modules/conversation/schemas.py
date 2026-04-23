from datetime import datetime

from pydantic import BaseModel

from app.modules.conversation.models import ConversationStatus, MessageSender


# ── Shared sub-schemas ────────────────────────────────────────────────────────


class StaffMemberOut(BaseModel):
    """Slim staff member representation embedded in conversation responses."""

    id: str
    display_name: str | None
    email: str

    model_config = {"from_attributes": True}


class AssignConversationRequest(BaseModel):
    """Body for PATCH /conversations/{id}/assign."""

    user_id: str | None = None  # None → unassign
    assigned_by_user_id: str | None = None


class AssignmentOut(BaseModel):
    conversation_id: str
    assigned_to: StaffMemberOut | None


# ── Reaction schemas ──────────────────────────────────────────────────────────


class ReactionOut(BaseModel):
    id: str
    user_id: str
    emoji: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ReactionCreate(BaseModel):
    """Body for POST /conversations/{id}/messages/{msg_id}/reactions."""

    emoji: str
    user_id: str


# ── Message schemas ───────────────────────────────────────────────────────────


class MessageCreate(BaseModel):
    sender_role: MessageSender
    content: str
    external_id: str | None = None


class MessageOut(BaseModel):
    id: str
    sender_role: str
    sender_identifier: str | None
    content: str
    external_id: str | None
    created_at: datetime
    reactions: list[ReactionOut] = []

    model_config = {"from_attributes": True}


class ConversationCreate(BaseModel):
    customer_identifier: str
    customer_name: str | None = None
    channel: str
    tenant_id: str


class ConversationOut(BaseModel):
    id: str
    tenant_id: str
    customer_identifier: str
    customer_name: str | None
    channel: str
    customer_id: str | None
    status: ConversationStatus
    assigned_to: StaffMemberOut | None = None
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut] = []

    model_config = {"from_attributes": True}


class LastMessage(BaseModel):
    content: str
    timestamp: datetime


class ConversationListItem(BaseModel):
    id: str
    customer_identifier: str
    customer_name: str | None
    status: ConversationStatus
    assigned_to: StaffMemberOut | None = None
    last_message: LastMessage | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationListResponse(BaseModel):
    items: list[ConversationListItem]
    next_cursor: str | None


class MessageListResponse(BaseModel):
    items: list[MessageOut]
    next_cursor: str | None
