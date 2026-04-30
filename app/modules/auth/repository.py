"""
app/modules/auth/repository.py

Data-access layer for User, Tenant, and UserTenant.

All methods are typed, async-first, and scoped to avoid N+1 queries.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.models.user import AuthProvider, Tenant, User, UserRole, UserTenant

logger = get_logger(__name__)


class AuthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── User ──────────────────────────────────────────────────────────────────

    async def get_user_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_user_by_phone(self, phone_number: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.phone_number == phone_number)
        )
        return result.scalar_one_or_none()

    async def create_user(
        self,
        *,
        email: str,
        password_hash: str | None,
        auth_provider: AuthProvider,
        display_name: str | None = None,
        phone_number: str | None = None,
    ) -> User:
        user = User(
            email=email,
            password_hash=password_hash,
            auth_provider=auth_provider,
            display_name=display_name,
            phone_number=phone_number,
        )
        self._session.add(user)
        await self._session.flush()  # populate user.id before returning
        logger.debug(
            "User created id=%s email=%s provider=%s", user.id, email, auth_provider
        )
        return user

    # ── Tenant ────────────────────────────────────────────────────────────────

    async def create_tenant(self, *, name: str | None = None) -> Tenant:
        tenant = Tenant(name=name)
        self._session.add(tenant)
        await self._session.flush()
        logger.debug("Tenant created id=%s name=%s", tenant.id, name)
        return tenant

    # ── UserTenant ────────────────────────────────────────────────────────────

    async def get_user_tenant(self, *, user_id: str) -> UserTenant | None:
        """Return the first tenant membership for a user (used for existing Google users)."""
        result = await self._session.execute(
            select(UserTenant).where(UserTenant.user_id == user_id).limit(1)
        )
        return result.scalar_one_or_none()

    async def get_owner_tenant_or_first(self, *, user_id: str) -> UserTenant | None:
        """Return the user's owner tenant; fall back to any tenant on first login."""
        result = await self._session.execute(
            select(UserTenant)
            .where(UserTenant.user_id == user_id)
            .order_by(
                UserTenant.role
            )  # "owner" < "member" lexicographically → owner first
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create_user_tenant(
        self,
        *,
        user_id: str,
        tenant_id: str,
        role: UserRole = UserRole.OWNER,
    ) -> UserTenant:
        link = UserTenant(user_id=user_id, tenant_id=tenant_id, role=role)
        self._session.add(link)
        await self._session.flush()
        logger.debug(
            "UserTenant created user=%s tenant=%s role=%s", user_id, tenant_id, role
        )
        return link
