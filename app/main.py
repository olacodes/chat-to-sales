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
from app.infra.database import create_all_tables, dispose_engine
from app.modules.conversation.handlers import register_message_received_handler
from app.modules.orders.handlers import register_order_intent_handler
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

logger = get_logger(__name__)
settings = get_settings()


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s [%s]", settings.APP_NAME, settings.ENVIRONMENT)
    await init_redis()

    # Ensure all tables exist. In production, remove this and rely on Alembic.
    await create_all_tables()
    logger.info("Database tables verified/created")

    # Start Redis event consumers for the default tenant.
    # TODO: fetch active tenant IDs from DB and register one task each.
    _listener_tasks = []
    _tenant_id = settings.TENANT_ID
    _listener_tasks.append(register_message_received_handler(_tenant_id))
    _listener_tasks.append(register_order_intent_handler(_tenant_id))
    _listener_tasks.append(register_payment_confirmed_handler(_tenant_id))
    _listener_tasks.append(register_realtime_listener(_tenant_id, ws_manager))
    _listener_tasks.append(register_order_created_notification_handler(_tenant_id))
    _listener_tasks.append(
        register_order_state_changed_notification_handler(_tenant_id)
    )
    _listener_tasks.append(register_payment_confirmed_notification_handler(_tenant_id))
    logger.info("Event listeners started for tenant=%s", _tenant_id)

    yield

    logger.info("Shutting down %s", settings.APP_NAME)
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_HOSTS,
        allow_credentials=True,
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
