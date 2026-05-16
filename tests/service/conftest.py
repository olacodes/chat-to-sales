"""
Shared fixtures for Layer 2 service tests.

Uses SQLite in-memory for the DB and fakeredis for Redis.
No external services needed — tests run in milliseconds.
"""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, patch

try:
    from fakeredis.aioredis import FakeServer, FakeRedis
except (ImportError, AttributeError):
    from fakeredis import FakeServer, FakeRedis
import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Import models in dependency order so SQLAlchemy mapper resolves all references
from app.core.models.user import User  # noqa: F401 — needed for Conversation FK
from app.modules.conversation.models import Conversation  # noqa: F401
from app.modules.orders.models import Order, OrderItem, OrderState
from app.modules.credit_sales.models import CreditSale
from app.modules.orders.customer_routing import CustomerTraderRouting
from app.modules.orders.product_images import ProductImage  # noqa: F401
from app.modules.orders.product_descriptions import ProductDescription  # noqa: F401
from app.modules.onboarding.models import Trader  # noqa: F401
from app.modules.reports.models import TenantReportConfig, WeeklyReport  # noqa: F401
from app.modules.payments.models import Payment  # noqa: F401
from app.modules.onboarding.analytics import OnboardingEvent  # noqa: F401
from app.modules.channels.models import TenantChannel  # noqa: F401
from app.modules.marketing.models import CustomerListEntry, Broadcast, BroadcastRecipient  # noqa: F401
from app.modules.marketing.followup import InterestEvent  # noqa: F401

# ── SQLite async engine ──────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_engine():
    """Create an in-memory SQLite engine with all tables."""
    from app.infra.database import Base

    engine = create_async_engine("sqlite+aiosqlite://", echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """Provide a clean DB session for each test."""
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


# ── Fake Redis ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def fake_redis():
    """Provide a fakeredis instance and patch get_redis() to return it."""
    server = FakeServer()
    redis = FakeRedis(server=server, decode_responses=True)
    with patch("app.infra.cache.get_redis", return_value=redis):
        # Also patch anywhere session.py imports get_redis
        with patch("app.modules.orders.session.get_redis", return_value=redis):
            yield redis
    if hasattr(redis, "aclose"):
        await redis.aclose()
    elif hasattr(redis, "close"):
        await redis.close()


# ── Order helpers ────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def sample_order(db_session: AsyncSession):
    """Create a sample INQUIRY order."""
    order = Order(
        tenant_id="test-tenant",
        conversation_id="conv-1",
        customer_phone="2348166041471",
        customer_name="Sodiq Olatunde",
        trader_phone="2348141605756",
        state=OrderState.INQUIRY,
        amount=Decimal("500000"),
        currency="NGN",
    )
    db_session.add(order)
    await db_session.flush()

    item = OrderItem(
        order_id=order.id,
        product_name="UK 14 Pro Max + eSIM",
        quantity=1,
        unit_price=Decimal("500000"),
    )
    db_session.add(item)
    await db_session.flush()

    return order


@pytest_asyncio.fixture
async def confirmed_order(db_session: AsyncSession, sample_order: Order):
    """Create a CONFIRMED order."""
    sample_order.state = OrderState.CONFIRMED
    await db_session.flush()
    return sample_order


@pytest_asyncio.fixture
async def mock_notification():
    """Mock NotificationService so no WhatsApp messages are sent."""
    with patch("app.modules.orders.service.NotificationService") as mock:
        instance = AsyncMock()
        mock.return_value = instance
        yield instance
