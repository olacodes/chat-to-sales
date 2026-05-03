"""
Shared dependency providers injected via FastAPI's Depends().

Usage:
    from app.core.dependencies import get_db, get_settings, CurrentUserDep

    @router.get("/")
    async def endpoint(
        user: CurrentUserDep,
        db: AsyncSession = Depends(get_db),
    ):
        ...
"""

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.infra.auth_utils import decode_access_token
from app.infra.database import async_session_factory


# ── Settings ──────────────────────────────────────────────────────────────────

SettingsDep = Annotated[Settings, Depends(get_settings)]


# ── Database session ──────────────────────────────────────────────────────────


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a transactional async database session per request."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


DBSessionDep = Annotated[AsyncSession, Depends(get_db)]


# ── Authentication ────────────────────────────────────────────────────────────

_bearer_scheme = HTTPBearer(auto_error=True)


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """Claims extracted from a verified JWT."""

    user_id: str
    tenant_id: str
    email: str
    is_superadmin: bool = False


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
) -> AuthenticatedUser:
    """
    Verify the Bearer JWT and return the authenticated user's claims.

    Raises UnauthorizedError (401) if the token is missing, malformed, or expired.
    """
    try:
        payload = decode_access_token(credentials.credentials)
    except JWTError:
        raise UnauthorizedError("Invalid or expired token")

    user_id: str | None = payload.get("sub")
    tenant_id: str | None = payload.get("tenant_id")
    email: str = payload.get("email", "")

    if not user_id or not tenant_id:
        raise UnauthorizedError("Invalid token claims")

    return AuthenticatedUser(
        user_id=user_id,
        tenant_id=tenant_id,
        email=email,
        is_superadmin=payload.get("is_superadmin", False),
    )


CurrentUserDep = Annotated[AuthenticatedUser, Depends(get_current_user)]


# ── Superadmin guard ─────────────────────────────────────────────────────────


async def require_superadmin(user: CurrentUserDep) -> AuthenticatedUser:
    """Raise 403 if the current user is not a platform superadmin."""
    if not user.is_superadmin:
        raise ForbiddenError("Superadmin access required.")
    return user


SuperAdminDep = Annotated[AuthenticatedUser, Depends(require_superadmin)]
