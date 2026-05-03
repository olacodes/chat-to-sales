"""
app/modules/admin/router.py

Superadmin backoffice endpoints — cross-tenant views for the platform owner.

All routes require a JWT with is_superadmin=True (enforced by SuperAdminDep).
"""

from decimal import Decimal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core.dependencies import DBSessionDep, SuperAdminDep
from app.modules.admin.repository import AdminRepository

router = APIRouter(prefix="/admin", tags=["Admin"])


# ── Response schemas ─────────────────────────────────────────────────────────


class TraderOut(BaseModel):
    id: str
    phone_number: str
    business_name: str | None
    business_category: str | None
    store_slug: str | None
    onboarding_status: str
    tier: str
    tenant_id: str | None
    created_at: str | None


class TraderListResponse(BaseModel):
    traders: list[TraderOut]
    total: int


class OrderItemOut(BaseModel):
    product_name: str
    quantity: int
    unit_price: Decimal


class OrderOut(BaseModel):
    id: str
    tenant_id: str
    conversation_id: str
    customer_phone: str | None
    trader_phone: str | None
    state: str
    amount: Decimal | None
    currency: str
    items: list[OrderItemOut]
    created_at: str | None


class OrderListResponse(BaseModel):
    orders: list[OrderOut]
    total: int


class PlatformMetrics(BaseModel):
    total_traders: int
    total_orders: int
    total_revenue: Decimal
    orders_today: int
    orders_this_week: int
    active_conversations: int


# ── Helpers ──────────────────────────────────────────────────────────────────


def _trader_out(t) -> TraderOut:
    return TraderOut(
        id=t.id,
        phone_number=t.phone_number,
        business_name=t.business_name,
        business_category=t.business_category,
        store_slug=t.store_slug,
        onboarding_status=t.onboarding_status,
        tier=t.tier,
        tenant_id=t.tenant_id,
        created_at=t.created_at.isoformat() if t.created_at else None,
    )


def _order_out(o) -> OrderOut:
    return OrderOut(
        id=o.id,
        tenant_id=o.tenant_id,
        conversation_id=o.conversation_id,
        customer_phone=o.customer_phone,
        trader_phone=o.trader_phone,
        state=o.state,
        amount=o.amount,
        currency=o.currency,
        items=[
            OrderItemOut(
                product_name=item.product_name,
                quantity=item.quantity,
                unit_price=item.unit_price,
            )
            for item in o.items
        ],
        created_at=o.created_at.isoformat() if o.created_at else None,
    )


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/metrics", summary="Platform-wide metrics")
async def get_metrics(
    _admin: SuperAdminDep,
    db: DBSessionDep,
) -> PlatformMetrics:
    repo = AdminRepository(db)
    data = await repo.get_platform_metrics()
    return PlatformMetrics(**data)


@router.get("/traders", summary="List all traders")
async def list_traders(
    _admin: SuperAdminDep,
    db: DBSessionDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> TraderListResponse:
    repo = AdminRepository(db)
    traders, total = await repo.list_traders(limit=limit, offset=offset)
    return TraderListResponse(
        traders=[_trader_out(t) for t in traders],
        total=total,
    )


@router.get("/traders/{phone}/orders", summary="Orders for a specific trader")
async def get_trader_orders(
    phone: str,
    _admin: SuperAdminDep,
    db: DBSessionDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> OrderListResponse:
    repo = AdminRepository(db)
    orders, total = await repo.get_trader_orders(
        trader_phone=phone,
        limit=limit,
        offset=offset,
    )
    return OrderListResponse(
        orders=[_order_out(o) for o in orders],
        total=total,
    )


@router.get("/orders", summary="All orders across all traders")
async def list_orders(
    _admin: SuperAdminDep,
    db: DBSessionDep,
    state: str | None = Query(None),
    trader_phone: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> OrderListResponse:
    repo = AdminRepository(db)
    orders, total = await repo.list_all_orders(
        state=state,
        trader_phone=trader_phone,
        limit=limit,
        offset=offset,
    )
    return OrderListResponse(
        orders=[_order_out(o) for o in orders],
        total=total,
    )
