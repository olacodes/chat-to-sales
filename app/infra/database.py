from datetime import datetime, timezone

from sqlalchemy import DateTime, String, func, text
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import get_settings

_settings = get_settings()

# ── Engine ────────────────────────────────────────────────────────────────────

engine = create_async_engine(
    _settings.database_url_str,
    echo=_settings.is_development,
    pool_pre_ping=True,  # recycle stale connections
    pool_size=10,
    max_overflow=20,
    connect_args={
        # asyncpg: enforce statement timeout (10 s) to prevent runaway queries
        "server_settings": {"statement_timeout": "10000"},
    },
)

# ── Session factory ───────────────────────────────────────────────────────────

async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,  # avoids lazy-load errors after commit
    autoflush=False,
)


# ── Declarative base ──────────────────────────────────────────────────────────


class Base(AsyncAttrs, DeclarativeBase):
    """
    All SQLAlchemy ORM models must inherit from this class.

    Provides:
    - AsyncAttrs mixin for awaitable relationship loading
    - A consistent __repr__ for debugging
    """

    def __repr__(self) -> str:  # pragma: no cover
        cols = ", ".join(
            f"{c.key}={getattr(self, c.key)!r}" for c in self.__table__.columns
        )
        return f"<{type(self).__name__}({cols})>"


# ── Timestamp mixin ───────────────────────────────────────────────────────────


class TimestampMixin:
    """
    Adds server-side created_at / updated_at columns to any model.

    Usage:
        class MyModel(TimestampMixin, Base):
            __tablename__ = "my_table"
            ...
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ── Helpers (dev / test only) ─────────────────────────────────────────────────


async def create_all_tables() -> None:
    """Create all tables directly — dev / test only. Use Alembic in production."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_all_tables() -> None:
    """Drop all tables — test teardown only."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def dispose_engine() -> None:
    """Close all pooled connections. Call on application shutdown."""
    await engine.dispose()
