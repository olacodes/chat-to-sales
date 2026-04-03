"""
Shared dependency providers injected via FastAPI's Depends().

Usage:
    from app.core.dependencies import get_db, get_settings

    @router.get("/")
    async def endpoint(db: AsyncSession = Depends(get_db)):
        ...
"""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
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
