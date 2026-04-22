"""
app/modules/staff/router.py

GET /staff/ — list all staff members (users) for a tenant.

Used by the assignment dropdown in the frontend to populate the list of
people a conversation can be assigned to.
"""

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from fastapi import APIRouter

from app.core.dependencies import DBSessionDep
from app.core.models.user import User, UserTenant
from app.modules.staff.schemas import StaffListResponse, StaffMemberOut

router = APIRouter(prefix="/staff", tags=["Staff"])


@router.get("")
async def list_staff(
    tenant_id: str,
    db: DBSessionDep,
) -> StaffListResponse:
    """Return all users who belong to the given tenant."""
    result = await db.execute(
        select(UserTenant)
        .options(joinedload(UserTenant.user))
        .where(UserTenant.tenant_id == tenant_id)
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
