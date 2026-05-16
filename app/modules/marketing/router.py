"""
app/modules/marketing/router.py

Dashboard API endpoints for customers and broadcasts.

  GET /marketing/customers          — paginated customer list with segments
  GET /marketing/customers/{phone}  — single customer detail
  GET /marketing/broadcasts         — broadcast history
  GET /marketing/broadcasts/{id}    — single broadcast with recipients
  GET /marketing/segments           — segment counts for the trader
"""

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import AuthenticatedUser, CurrentUserDep, DBSessionDep
from app.modules.marketing.models import (
    Broadcast,
    BroadcastRecipient,
    BroadcastStatus,
    CustomerListEntry,
)
from app.modules.orders.models import Order, OrderState

router = APIRouter(prefix="/marketing", tags=["Marketing"])


# ── Response schemas ─────────────────────────────────────────────────────────


class CustomerOut(BaseModel):
    id: str
    customer_phone: str
    customer_name: str | None
    total_orders: int
    total_spend: float
    first_order_date: datetime | None
    last_order_date: datetime | None
    opted_out: bool
    segments: list[str] | None
    last_broadcast_at: datetime | None


class CustomerListResponse(BaseModel):
    items: list[CustomerOut]
    total: int
    limit: int
    offset: int


class CustomerDetailOut(CustomerOut):
    recent_orders: list[dict]


class BroadcastOut(BaseModel):
    id: str
    segment: str
    message_text: str
    original_text: str | None
    total_recipients: int
    sent_count: int
    delivered_count: int
    read_count: int
    reply_count: int
    order_count: int
    order_revenue: float
    status: str
    created_at: datetime
    completed_at: datetime | None


class BroadcastListResponse(BaseModel):
    items: list[BroadcastOut]
    total: int
    limit: int
    offset: int


class BroadcastDetailOut(BroadcastOut):
    recipients: list[dict]


class SegmentCountOut(BaseModel):
    segment: str
    label: str
    count: int


class SegmentCountsResponse(BaseModel):
    total_customers: int
    segments: list[SegmentCountOut]


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _get_trader_phone(user: AuthenticatedUser, db: AsyncSession) -> str:
    """Look up the trader's phone number from the User record."""
    from app.core.models.user import User
    result = await db.execute(
        select(User.phone_number).where(User.id == user.user_id)
    )
    phone = result.scalar_one_or_none()
    if phone:
        return phone
    # Fallback: try Trader table by tenant
    from app.modules.onboarding.repository import TraderRepository
    repo = TraderRepository(db)
    trader = await repo.get_by_tenant(user.tenant_id)
    if trader:
        return trader.phone_number
    return ""


_SEGMENT_LABELS = {
    "all_customers": "All Customers",
    "vip": "VIP Customers",
    "repeat_buyer": "Repeat Buyers",
    "paid_once": "Bought Once",
    "new_lead": "New Leads",
    "lapsed": "Lapsed Customers",
    "abandoned_cart": "Abandoned Cart",
    "browsed_only": "Browsed Only",
    "diverse_buyer": "Diverse Buyers",
    "price_sensitive": "Price Sensitive",
    "premium": "Premium Buyers",
    "weekly": "Weekly Shoppers",
    "monthly": "Monthly Shoppers",
    "payday": "Payday Buyers",
    "weekend": "Weekend Shoppers",
}


# ── Customers ────────────────────────────────────────────────────────────────


@router.get("/customers", response_model=CustomerListResponse)
async def list_customers(
    user: CurrentUserDep,
    db: DBSessionDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None),
    segment: str | None = Query(None),
) -> CustomerListResponse:
    """List customers for the authenticated trader."""
    trader_phone = await _get_trader_phone(user, db)

    base = select(CustomerListEntry).where(
        CustomerListEntry.trader_phone == trader_phone,
    )

    if search:
        term = f"%{search}%"
        base = base.where(
            (CustomerListEntry.customer_name.ilike(term))
            | (CustomerListEntry.customer_phone.ilike(term))
        )

    # Count total
    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    # Filter by segment if specified
    # Since segments is JSONB, we filter in Python after fetch
    # For performance at scale, could add a GIN index
    stmt = base.order_by(CustomerListEntry.last_order_date.desc().nullslast())

    if segment and segment != "all_customers":
        # Fetch all and filter (segments is JSONB array)
        result = await db.execute(stmt)
        all_entries = list(result.scalars().all())
        filtered = [e for e in all_entries if e.segments and segment in e.segments]
        total = len(filtered)
        entries = filtered[offset : offset + limit]
    else:
        stmt = stmt.offset(offset).limit(limit)
        result = await db.execute(stmt)
        entries = list(result.scalars().all())

    items = [
        CustomerOut(
            id=e.id,
            customer_phone=e.customer_phone,
            customer_name=e.customer_name,
            total_orders=e.total_orders,
            total_spend=float(e.total_spend),
            first_order_date=e.first_order_date,
            last_order_date=e.last_order_date,
            opted_out=e.opted_out,
            segments=e.segments,
            last_broadcast_at=e.last_broadcast_at,
        )
        for e in entries
    ]

    return CustomerListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/customers/{phone}", response_model=CustomerDetailOut)
async def get_customer(
    phone: str,
    user: CurrentUserDep,
    db: DBSessionDep,
) -> CustomerDetailOut:
    """Get a single customer with recent orders."""
    trader_phone = await _get_trader_phone(user, db)

    result = await db.execute(
        select(CustomerListEntry).where(
            CustomerListEntry.trader_phone == trader_phone,
            CustomerListEntry.customer_phone == phone,
        )
    )
    entry = result.scalar_one_or_none()
    if not entry:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("Customer", phone)

    # Fetch recent orders
    orders_result = await db.execute(
        select(Order)
        .where(
            Order.trader_phone == trader_phone,
            Order.customer_phone == phone,
        )
        .order_by(Order.created_at.desc())
        .limit(20)
    )
    orders = list(orders_result.scalars().all())

    recent_orders = [
        {
            "id": o.id,
            "ref": o.id[:8],
            "state": o.state,
            "amount": float(o.amount) if o.amount else 0,
            "is_credit": o.is_credit,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for o in orders
    ]

    return CustomerDetailOut(
        id=entry.id,
        customer_phone=entry.customer_phone,
        customer_name=entry.customer_name,
        total_orders=entry.total_orders,
        total_spend=float(entry.total_spend),
        first_order_date=entry.first_order_date,
        last_order_date=entry.last_order_date,
        opted_out=entry.opted_out,
        segments=entry.segments,
        last_broadcast_at=entry.last_broadcast_at,
        recent_orders=recent_orders,
    )


# ── Segments ─────────────────────────────────────────────────────────────────


@router.get("/segments", response_model=SegmentCountsResponse)
async def get_segment_counts(
    user: CurrentUserDep,
    db: DBSessionDep,
) -> SegmentCountsResponse:
    """Get segment counts for the broadcast picker."""
    from app.modules.marketing.customer_list import CustomerListService

    trader_phone = await _get_trader_phone(user, db)
    cl_svc = CustomerListService(db)
    counts = await cl_svc.get_segment_counts(trader_phone)

    total = counts.pop("all_customers", 0)
    segments = [
        SegmentCountOut(
            segment=seg,
            label=_SEGMENT_LABELS.get(seg, seg.replace("_", " ").title()),
            count=count,
        )
        for seg, count in counts.items()
        if count > 0
    ]
    # Sort by count descending
    segments.sort(key=lambda s: s.count, reverse=True)

    return SegmentCountsResponse(total_customers=total, segments=segments)


# ── Broadcasts ───────────────────────────────────────────────────────────────


@router.get("/broadcasts", response_model=BroadcastListResponse)
async def list_broadcasts(
    user: CurrentUserDep,
    db: DBSessionDep,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
) -> BroadcastListResponse:
    """List broadcast history for the authenticated trader."""
    trader_phone = await _get_trader_phone(user, db)

    base = select(Broadcast).where(Broadcast.trader_phone == trader_phone)
    if status:
        base = base.where(Broadcast.status == status)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = base.order_by(Broadcast.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    broadcasts = list(result.scalars().all())

    items = [
        BroadcastOut(
            id=b.id,
            segment=b.segment,
            message_text=b.message_text,
            original_text=b.original_text,
            total_recipients=b.total_recipients,
            sent_count=b.sent_count,
            delivered_count=b.delivered_count,
            read_count=b.read_count,
            reply_count=b.reply_count,
            order_count=b.order_count,
            order_revenue=float(b.order_revenue),
            status=b.status,
            created_at=b.created_at,
            completed_at=b.completed_at,
        )
        for b in broadcasts
    ]

    return BroadcastListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/broadcasts/{broadcast_id}", response_model=BroadcastDetailOut)
async def get_broadcast(
    broadcast_id: str,
    user: CurrentUserDep,
    db: DBSessionDep,
) -> BroadcastDetailOut:
    """Get a single broadcast with recipient details."""
    trader_phone = await _get_trader_phone(user, db)

    result = await db.execute(
        select(Broadcast).where(
            Broadcast.id == broadcast_id,
            Broadcast.trader_phone == trader_phone,
        )
    )
    broadcast = result.scalar_one_or_none()
    if not broadcast:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("Broadcast", broadcast_id)

    recipients_result = await db.execute(
        select(BroadcastRecipient).where(
            BroadcastRecipient.broadcast_id == broadcast_id,
        ).order_by(BroadcastRecipient.sent_at.desc().nullslast())
    )
    recipients = list(recipients_result.scalars().all())

    recipient_list = [
        {
            "customer_phone": r.customer_phone,
            "customer_name": r.customer_name,
            "status": r.status,
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            "delivered_at": r.delivered_at.isoformat() if r.delivered_at else None,
            "read_at": r.read_at.isoformat() if r.read_at else None,
            "replied_at": r.replied_at.isoformat() if r.replied_at else None,
            "skip_reason": r.skip_reason,
        }
        for r in recipients
    ]

    return BroadcastDetailOut(
        id=broadcast.id,
        segment=broadcast.segment,
        message_text=broadcast.message_text,
        original_text=broadcast.original_text,
        total_recipients=broadcast.total_recipients,
        sent_count=broadcast.sent_count,
        delivered_count=broadcast.delivered_count,
        read_count=broadcast.read_count,
        reply_count=broadcast.reply_count,
        order_count=broadcast.order_count,
        order_revenue=float(broadcast.order_revenue),
        status=broadcast.status,
        created_at=broadcast.created_at,
        completed_at=broadcast.completed_at,
        recipients=recipient_list,
    )
