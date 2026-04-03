"""
Alembic migration environment — async (asyncpg) version.

Key design decisions:
- DATABASE_URL is read from app settings, never hardcoded in alembic.ini.
- All model modules are imported here so autogenerate can detect schema changes.
- Both offline and online modes use the same URL source.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ── App imports ───────────────────────────────────────────────────────────────
# Import settings first so DATABASE_URL is resolved from .env
from app.core.config import get_settings

# Import Base so its metadata is populated, then import every model module so
# Alembic knows about all tables when autogenerating revisions.
from app.infra.database import Base  # noqa: F401 — registers metadata

# -- model imports (add a new line here whenever you add a new module) ---------
import app.core.models.customer  # noqa: F401
import app.modules.conversation.models  # noqa: F401
import app.modules.orders.models  # noqa: F401
import app.modules.payments.models  # noqa: F401

# -----------------------------------------------------------------------------

# ── Alembic config ────────────────────────────────────────────────────────────
alembic_cfg = context.config

# Wire DATABASE_URL from app settings into alembic (overrides alembic.ini value)
_settings = get_settings()
alembic_cfg.set_main_option("sqlalchemy.url", _settings.database_url_str)

# Configure Python logging from alembic.ini [loggers] section
if alembic_cfg.config_file_name is not None:
    fileConfig(alembic_cfg.config_file_name)

target_metadata = Base.metadata


# ── Offline migrations ────────────────────────────────────────────────────────


def run_migrations_offline() -> None:
    """
    Emit SQL to stdout without a live DB connection.
    Useful for reviewing or applying migrations on a restricted DB.
    """
    url = alembic_cfg.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online migrations (async) ─────────────────────────────────────────────────


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,  # detect column type changes
        compare_server_default=True,  # detect server_default changes
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create a temporary async engine and run migrations inside a sync callback."""
    connectable = async_engine_from_config(
        alembic_cfg.get_section(alembic_cfg.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # no pooling during migrations
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


# ── Entry point ───────────────────────────────────────────────────────────────

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
