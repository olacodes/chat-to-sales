from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.exceptions import (
    ChatToSalesError,
    chattosales_error_handler,
    unhandled_error_handler,
)
from app.core.logging import get_logger
from app.infra.cache import close_redis, init_redis
from app.infra.crypto import encrypt_token
from app.infra.database import async_session_factory, create_all_tables, dispose_engine
from app.infra.scheduler import start_scheduler, stop_scheduler
from app.modules.conversation.handlers import register_message_received_handler
from app.modules.orders.handlers import register_order_intent_handler, register_credit_sale_status_handler
from app.modules.onboarding.handlers import register_onboarding_handler
from app.modules.onboarding.models import Trader  # noqa: F401 — registers model with Base
from app.modules.onboarding.router import router as store_router
from app.modules.payments.handlers import register_payment_confirmed_handler
from app.modules.notifications.handlers import (
    register_order_created_notification_handler,
    register_order_state_changed_notification_handler,
    register_payment_confirmed_notification_handler,
)
from app.modules.realtime.router import manager as ws_manager
from app.modules.realtime.router import router as realtime_router
from app.modules.realtime.service import register_realtime_listener
from app.modules.conversation.router import router as conversation_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.channels.router import router as channels_router
from app.modules.channels.models import (
    TenantChannel,
)  # noqa: F401 — registers model with Base
from app.modules.ingestion.router import router as ingestion_router
from app.modules.auth.router import router as auth_router
from app.core.models.user import (
    User,
    Tenant,
    UserTenant,
)  # noqa: F401 — registers models with Base
from app.modules.notifications.router import router as notifications_router
from app.modules.orders.router import router as orders_router
from app.modules.payments.router import router as payments_router
from app.modules.staff.router import router as staff_router
from app.modules.reports.router import router as reports_router
from app.modules.reports.models import (  # noqa: F401 — registers models with Base
    TenantReportConfig,
    WeeklyReport,
)
from app.modules.admin.router import router as admin_router
from app.modules.credit_sales.router import router as credit_sales_router
from app.modules.credit_sales.models import CreditSale  # noqa: F401 — registers model with Base

logger = get_logger(__name__)
settings = get_settings()


# ── Platform channel seed ─────────────────────────────────────────────────────


async def _seed_platform_channel() -> None:
    """
    Ensure the platform tenant's WhatsApp channel exists in the DB.

    Reads TENANT_ID, WHATSAPP_PHONE_NUMBER_ID, and WHATSAPP_ACCESS_TOKEN
    from settings. If all three are set and no channel record exists yet,
    creates one so the app can send/receive messages immediately after a
    fresh database without any manual setup.
    """
    tenant_id = settings.TENANT_ID
    phone_id = settings.WHATSAPP_PHONE_NUMBER_ID
    token = settings.WHATSAPP_ACCESS_TOKEN

    if not tenant_id or not phone_id or not token:
        logger.debug("Platform channel seed skipped — credentials not fully configured")
        return

    from app.modules.channels.repository import ChannelRepository

    async with async_session_factory() as session:
        repo = ChannelRepository(session)
        existing = await repo.get_by_tenant_and_channel(
            tenant_id=tenant_id, channel="whatsapp",
        )
        if existing:
            return

        encrypted = encrypt_token(token)
        await repo.upsert(
            tenant_id=tenant_id,
            channel="whatsapp",
            phone_number_id=phone_id,
            encrypted_access_token=encrypted,
            webhook_registered=True,
        )
        await session.commit()
        logger.info(
            "Platform WhatsApp channel seeded — tenant=%s phone_number_id=%s",
            tenant_id,
            phone_id,
        )


# ── Superadmin seed ───────────────────────────────────────────────────────────


async def _seed_superadmin() -> None:
    """
    Auto-create (or upgrade) the platform superadmin account at startup.

    Reads ADMIN_PHONE, ADMIN_EMAIL, and ADMIN_PASSWORD from settings.
    If all three are set:
      - User does not exist → create User + Tenant + UserTenant (is_superadmin=True)
      - User exists but not superadmin → upgrade to superadmin
      - User is already superadmin → skip silently
    """
    phone = settings.ADMIN_PHONE
    email = settings.ADMIN_EMAIL
    password = settings.ADMIN_PASSWORD

    if not phone or not email or not password:
        logger.debug("Superadmin seed skipped — ADMIN_PHONE/EMAIL/PASSWORD not fully configured")
        return

    import re
    phone = re.sub(r"\D", "", phone)

    from app.core.models.user import AuthProvider, UserRole
    from app.infra.auth_utils import hash_password
    from app.modules.auth.repository import AuthRepository

    async with async_session_factory.begin() as session:
        repo = AuthRepository(session)
        existing = await repo.get_user_by_phone(phone)

        if existing is not None:
            if existing.is_superadmin:
                return  # already set up
            existing.is_superadmin = True
            session.add(existing)
            logger.info("Superadmin flag set on existing user=%s phone=%s", existing.id, phone)
            return

        user = await repo.create_user(
            email=email,
            password_hash=hash_password(password),
            auth_provider=AuthProvider.EMAIL,
            display_name="Platform Admin",
            phone_number=phone,
        )
        user.is_superadmin = True
        session.add(user)
        await session.flush()

        tenant = await repo.create_tenant(name="ChatToSales Admin")
        await repo.create_user_tenant(
            user_id=user.id,
            tenant_id=tenant.id,
            role=UserRole.OWNER,
        )
        logger.info(
            "Superadmin seeded — user=%s tenant=%s phone=%s email=%s",
            user.id,
            tenant.id,
            phone,
            email,
        )


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s [%s]", settings.APP_NAME, settings.ENVIRONMENT)
    await init_redis()

    # Ensure all tables exist. In production, remove this and rely on Alembic.
    await create_all_tables()
    logger.info("Database tables verified/created")

    # Auto-seed the platform WhatsApp channel from env vars so the app
    # works immediately after a fresh DB without manual API calls.
    await _seed_platform_channel()

    # Auto-seed the superadmin account from env vars.
    await _seed_superadmin()

    # Start Redis event consumers — one task per event type, all tenants.
    # Using PSUBSCRIBE pattern matching, each task automatically handles
    # events from every tenant including those created after startup.
    _listener_tasks = []
    _listener_tasks.append(register_message_received_handler())
    _listener_tasks.append(register_onboarding_handler())
    _listener_tasks.append(register_order_intent_handler())
    _listener_tasks.append(register_credit_sale_status_handler())
    _listener_tasks.append(register_payment_confirmed_handler())
    _listener_tasks.append(register_realtime_listener(ws_manager))
    _listener_tasks.append(register_order_created_notification_handler())
    _listener_tasks.append(register_order_state_changed_notification_handler())
    _listener_tasks.append(register_payment_confirmed_notification_handler())
    logger.info("Event listeners started (all tenants via pattern subscription)")

    start_scheduler()

    yield

    logger.info("Shutting down %s", settings.APP_NAME)
    stop_scheduler()
    for task in _listener_tasks:
        task.cancel()
    await close_redis()
    await dispose_engine()


# ── Application factory ───────────────────────────────────────────────────────


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── Middleware ────────────────────────────────────────────────────────────
    # allow_credentials=True is incompatible with allow_origins=["*"] — the
    # browser requires the server to echo the specific origin when credentials
    # are enabled.  Only enable credentials when explicit origins are set.
    origins = settings.ALLOWED_HOSTS
    use_credentials = origins != ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=use_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Exception handlers ────────────────────────────────────────────────────
    app.add_exception_handler(ChatToSalesError, chattosales_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_error_handler)  # type: ignore[arg-type]

    # ── Routers ───────────────────────────────────────────────────────────────
    prefix = settings.API_PREFIX
    app.include_router(auth_router, prefix=prefix)
    app.include_router(ingestion_router, prefix=prefix)
    app.include_router(channels_router, prefix=prefix)
    app.include_router(conversation_router, prefix=prefix)
    app.include_router(dashboard_router, prefix=prefix)
    app.include_router(orders_router, prefix=prefix)
    app.include_router(payments_router, prefix=prefix)
    app.include_router(notifications_router, prefix=prefix)
    app.include_router(staff_router, prefix=prefix)
    app.include_router(reports_router, prefix=prefix)
    app.include_router(credit_sales_router, prefix=prefix)
    app.include_router(store_router, prefix=prefix)
    app.include_router(admin_router, prefix=prefix)
    app.include_router(realtime_router)  # no API prefix — /ws/{tenant_id}

    # ── Health check ──────────────────────────────────────────────────────────
    @app.get("/health", tags=["Health"], summary="Health check")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
        }

    return app


app = create_app()
