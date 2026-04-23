from datetime import datetime

from pydantic import BaseModel, EmailStr


class StaffMemberOut(BaseModel):
    id: str
    display_name: str | None
    email: str
    role: str

    model_config = {"from_attributes": True}


class StaffListResponse(BaseModel):
    items: list[StaffMemberOut]


class InviteCreateRequest(BaseModel):
    """Body for POST /staff/invite — owner requests an invite link."""

    role: str = "member"


class InviteOut(BaseModel):
    """Returned after generating an invite token."""

    token: str
    expires_at: datetime
    role: str


class InviteInfoOut(BaseModel):
    """Returned by GET /staff/invite/{token} — let the frontend show context."""

    token: str
    role: str
    tenant_id: str


class AcceptInviteRequest(BaseModel):
    """Body for POST /staff/invite/{token}/accept."""

    name: str
    email: EmailStr
    password: str
