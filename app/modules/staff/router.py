"""
app/modules/staff/router.py

Staff management endpoints.

Routes:
  GET    /staff/              — list all staff for a tenant
  POST   /staff/invite        — create an invite link (owner only)
  GET    /staff/invite/{token} — validate a token (public, no auth needed)
  POST   /staff/invite/{token}/accept — accept invite, create account + join tenant
  DELETE /staff/{user_id}     — remove a member from the tenant
"""

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.dependencies import CurrentUserDep, DBSessionDep
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.models.user import AuthProvider, InviteToken, User, UserRole, UserTenant
from app.infra.auth_utils import create_access_token, hash_password
from app.modules.staff.schemas import (
    AcceptInviteRequest,
    InviteCreateRequest,
    InviteInfoOut,
    InviteOut,
    StaffListResponse,
    StaffMemberOut,
)

router = APIRouter(prefix="/staff", tags=["Staff"])

_INVITE_TTL_HOURS = 72  # tokens expire after 3 days


# ── List members ──────────────────────────────────────────────────────────────


@router.get("")
async def list_staff(
    user: CurrentUserDep,
    db: DBSessionDep,
) -> StaffListResponse:
    """Return all users who belong to the given tenant."""
    result = await db.execute(
        select(UserTenant)
        .options(joinedload(UserTenant.user))
        .where(UserTenant.tenant_id == user.tenant_id)
        .order_by(UserTenant.created_at.asc())
    )
    memberships = result.scalars().all()

    items = [
        StaffMemberOut(
            id=m.user.id,
            display_name=m.user.display_name,
            email=m.user.email,
            role=m.role,
        )
        for m in memberships
        if m.user is not None
    ]
    return StaffListResponse(items=items)


# ── Create invite link ────────────────────────────────────────────────────────


@router.post("/invite", status_code=status.HTTP_201_CREATED)
async def create_invite(
    user: CurrentUserDep,
    body: InviteCreateRequest,
    db: DBSessionDep,
) -> InviteOut:
    """Generate a single-use invite token for this tenant."""
    token_value = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(hours=_INVITE_TTL_HOURS)

    invite = InviteToken(
        tenant_id=user.tenant_id,
        token=token_value,
        role=body.role,
        expires_at=expires_at,
    )
    db.add(invite)
    await db.flush()

    return InviteOut(token=token_value, expires_at=expires_at, role=body.role)


# ── Validate invite token (public) ────────────────────────────────────────────


@router.get("/invite/{token}")
async def get_invite(
    token: str,
    db: DBSessionDep,
) -> InviteInfoOut:
    """
    Validate an invite token and return context so the frontend can render
    the accept form.  Raises 404 for missing/expired/used tokens.
    """
    invite = await _load_valid_invite(token, db)
    return InviteInfoOut(token=invite.token, role=invite.role, tenant_id=invite.tenant_id)


# ── Accept invite ─────────────────────────────────────────────────────────────


@router.post("/invite/{token}/accept", status_code=status.HTTP_201_CREATED)
async def accept_invite(
    token: str,
    body: AcceptInviteRequest,
    db: DBSessionDep,
) -> dict:
    """
    Accept an invite: create a new user account and join the tenant.

    Returns a JWT so the new user is immediately logged in.
    """
    invite = await _load_valid_invite(token, db)

    # Check email not already registered
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise ConflictError(f"An account with email '{body.email}' already exists.")

    # Create the new user
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        auth_provider=AuthProvider.EMAIL,
        display_name=body.name or None,
    )
    db.add(user)
    await db.flush()

    # Link to tenant
    link = UserTenant(user_id=user.id, tenant_id=invite.tenant_id, role=invite.role)
    db.add(link)

    # Consume the token
    invite.used_at = datetime.now(UTC)
    await db.flush()

    access_token = create_access_token(
        user_id=user.id,
        tenant_id=invite.tenant_id,
        email=user.email,
    )

    return {
        "access_token": access_token,
        "user_id": user.id,
        "tenant_id": invite.tenant_id,
        "email": user.email,
    }


# ── Remove member ─────────────────────────────────────────────────────────────


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    user_id: str,
    user: CurrentUserDep,
    db: DBSessionDep,
) -> None:
    """Remove a staff member from the tenant.  Owners cannot be removed."""
    result = await db.execute(
        select(UserTenant).where(
            UserTenant.user_id == user_id,
            UserTenant.tenant_id == user.tenant_id,
        )
    )
    membership = result.scalar_one_or_none()
    if not membership:
        raise NotFoundError("Staff member", user_id)
    if membership.role == UserRole.OWNER:
        raise ForbiddenError("The workspace owner cannot be removed.")
    await db.delete(membership)


# ── Helper ────────────────────────────────────────────────────────────────────


async def _load_valid_invite(token: str, db: AsyncSession) -> InviteToken:
    """Load and validate an invite token; raise 404 if invalid."""
    result = await db.execute(
        select(InviteToken).where(InviteToken.token == token)
    )
    invite = result.scalar_one_or_none()

    now = datetime.now(UTC)
    if invite is None or invite.used_at is not None or invite.expires_at < now:
        raise NotFoundError("Invite token", token)

    return invite
