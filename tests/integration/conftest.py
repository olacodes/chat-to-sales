"""
Integration test fixtures.

Provides a FastAPI test client with:
- SQLite in-memory database (all tables)
- Fakeredis
- JWT auth override (no real login needed)
"""

from decimal import Decimal
from unittest.mock import patch

try:
    from fakeredis.aioredis import FakeServer, FakeRedis
except (ImportError, AttributeError):
    from fakeredis import FakeServer, FakeRedis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Import all models so Base.metadata knows about them
from app.core.models.user import User  # noqa: F401
from app.modules.conversation.models import Conversation  # noqa: F401
from app.modules.orders.models import Order, OrderItem, OrderState
from app.modules.credit_sales.models import CreditSale  # noqa: F401
from app.modules.orders.customer_routing import CustomerTraderRouting  # noqa: F401
from app.modules.orders.product_images import ProductImage  # noqa: F401
from app.modules.orders.product_descriptions import ProductDescription  # noqa: F401
from app.modules.onboarding.models import Trader  # noqa: F401
from app.modules.reports.models import TenantReportConfig, WeeklyReport  # noqa: F401
from app.modules.payments.models import Payment  # noqa: F401
from app.modules.onboarding.analytics import OnboardingEvent  # noqa: F401
from app.modules.channels.models import TenantChannel  # noqa: F401
from app.modules.marketing.models import CustomerListEntry, Broadcast, BroadcastRecipient  # noqa: F401
from app.modules.marketing.followup import InterestEvent  # noqa: F401

from app.infra.database import Base
from app.core.dependencies import AuthenticatedUser, get_current_user, get_db


# ── Test engine + session ────────────────────────────────────────────────────

_test_engine = None
_test_session_factory = None


async def _get_test_engine():
    global _test_engine, _test_session_factory
    if _test_engine is None:
        _test_engine = create_async_engine("sqlite+aiosqlite://", echo=False)

        @event.listens_for(_test_engine.sync_engine, "connect")
        def _pragma(dbapi_conn, _):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=OFF")
            cursor.close()

        async with _test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        _test_session_factory = async_sessionmaker(
            _test_engine, class_=AsyncSession, expire_on_commit=False,
        )
    return _test_engine


async def _override_get_db():
    """Yield a test DB session."""
    await _get_test_engine()
    async with _test_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def _override_get_current_user():
    """Return a fake authenticated user."""
    return AuthenticatedUser(
        user_id="test-user-id",
        tenant_id="test-tenant",
        email="test@chattosales.com",
        is_superadmin=False,
    )


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def _setup_db():
    """Ensure tables exist and clean them between tests."""
    engine = await _get_test_engine()
    # Truncate all tables before each test (ignore missing tables)
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            try:
                await conn.execute(table.delete())
            except Exception:
                pass  # Table may not exist in SQLite — skip
    yield


@pytest_asyncio.fixture
async def fake_redis():
    """Provide fakeredis and patch get_redis globally."""
    server = FakeServer()
    redis = FakeRedis(server=server, decode_responses=True)
    with patch("app.infra.cache.get_redis", return_value=redis):
        with patch("app.modules.orders.session.get_redis", return_value=redis):
            yield redis
    try:
        await redis.aclose()
    except (AttributeError, TypeError):
        try:
            await redis.close()
        except TypeError:
            redis.close()


@pytest_asyncio.fixture
async def client(fake_redis):
    """Provide an httpx AsyncClient with a lightweight test FastAPI app."""
    from fastapi import FastAPI
    from app.modules.dashboard.router import router as dashboard_router
    from app.modules.reports.router import router as reports_router
    from app.modules.marketing.router import router as marketing_router

    from app.core.exceptions import ChatToSalesError, chattosales_error_handler

    app = FastAPI()
    app.add_exception_handler(ChatToSalesError, chattosales_error_handler)  # type: ignore
    app.include_router(dashboard_router, prefix="/api/v1")
    app.include_router(reports_router, prefix="/api/v1")
    app.include_router(marketing_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = lambda: _override_get_current_user()

    # Patch _get_trader_phone to return a fixed phone for tests
    with patch(
        "app.modules.marketing.router._get_trader_phone",
        return_value="2348141605756",
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest_asyncio.fixture
async def db_session():
    """Direct DB session for seeding test data."""
    await _get_test_engine()
    async with _test_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def seed_orders(db_session: AsyncSession):
    """Seed a few orders for dashboard tests."""
    orders = []
    for i, (state, amount) in enumerate([
        (OrderState.INQUIRY, 100000),
        (OrderState.CONFIRMED, 200000),
        (OrderState.PAID, 300000),
        (OrderState.PAID, 150000),
        (OrderState.FAILED, 50000),
    ]):
        order = Order(
            tenant_id="test-tenant",
            conversation_id=f"conv-{i}",
            customer_phone=f"234800000000{i}",
            customer_name=f"Customer {i}",
            trader_phone="2348141605756",
            state=state,
            amount=Decimal(str(amount)),
            currency="NGN",
        )
        db_session.add(order)
    await db_session.commit()
    return orders


@pytest_asyncio.fixture
async def seed_customers(db_session: AsyncSession):
    """Seed customers for marketing API tests."""
    from app.modules.marketing.models import CustomerListEntry
    customers = [
        CustomerListEntry(
            tenant_id="test-tenant", trader_phone="2348141605756",
            customer_phone="2348001111111", customer_name="Bimpe Adeyemi",
            total_orders=5, total_spend=Decimal("250000"),
            segments=["vip", "weekend"],
        ),
        CustomerListEntry(
            tenant_id="test-tenant", trader_phone="2348141605756",
            customer_phone="2348002222222", customer_name="Ade Bakare",
            total_orders=2, total_spend=Decimal("15000"),
            segments=["repeat_buyer"],
        ),
        CustomerListEntry(
            tenant_id="test-tenant", trader_phone="2348141605756",
            customer_phone="2348003333333", customer_name="Mama Tayo",
            total_orders=1, total_spend=Decimal("5000"),
            segments=["paid_once"],
            opted_out=True,
        ),
    ]
    for c in customers:
        db_session.add(c)
    await db_session.commit()
    return customers


@pytest_asyncio.fixture
async def seed_broadcasts(db_session: AsyncSession):
    """Seed broadcasts for marketing API tests."""
    from app.modules.marketing.models import Broadcast, BroadcastStatus
    from datetime import datetime, timezone
    now = datetime.now(tz=timezone.utc)
    broadcasts = [
        Broadcast(
            tenant_id="test-tenant", trader_phone="2348141605756",
            segment="all_customers", message_text="Hello everyone!",
            original_text="hi all", total_recipients=10, sent_count=8,
            status=BroadcastStatus.SENT, completed_at=now,
        ),
        Broadcast(
            tenant_id="test-tenant", trader_phone="2348141605756",
            segment="vip", message_text="Special VIP offer!",
            total_recipients=3, sent_count=0,
            status=BroadcastStatus.DRAFT,
        ),
    ]
    for b in broadcasts:
        db_session.add(b)
    await db_session.commit()
    return broadcasts
