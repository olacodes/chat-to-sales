"""
app/modules/dashboard/router.py

Dashboard endpoints:
  GET /dashboard/metrics         — aggregate KPIs (1 SQL round-trip)
  GET /dashboard/recent-activity — unified activity feed (1 SQL round-trip)
  GET /dashboard/overview        — all data for the dashboard page (4 SQL round-trips)

overview query strategy
-----------------------
Runs 4 sequential queries (SQLAlchemy async sessions are not concurrent-safe):
  1. metrics       — cross-join of two single-row aggregate subqueries
  2. recent_orders — correlated scalar subquery for item_count; no N+1
  3. recent_conversations — two correlated subqueries (last_message content +
                            timestamp) embedded in the SELECT; no second query
  4. recent_payments — JOIN orders; same technique as the list endpoint

Four DB round-trips vs. N client-to-API calls: the net frontend benefit is
eliminating multiple HTTP requests and their associated latency.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import String, case, cast, func, literal, select, text, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import AuthenticatedUser, CurrentUserDep, DBSessionDep
from app.modules.conversation.models import Conversation, ConversationStatus, Message
from app.modules.credit_sales.models import CreditSale, CreditSaleStatus
from app.modules.orders.models import Order, OrderItem, OrderState
from app.modules.payments.models import Payment, PaymentStatus

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

_ACTIVITY_LIMIT = 20
_OVERVIEW_LIMIT = 5


def _tenant_filter(user: AuthenticatedUser) -> str | None:
    """Return None (no filter) for superadmins, tenant_id for everyone else."""
    return None if user.is_superadmin else user.tenant_id


# ── Response schema ───────────────────────────────────────────────────────────


class DashboardMetrics(BaseModel):
    total_orders: int
    total_revenue: Decimal
    active_conversations: int
    conversion_rate: float
    total_outstanding: Decimal = Decimal("0")
    active_debts_count: int = 0
    overdue_debts_count: int = 0


# ── Query ─────────────────────────────────────────────────────────────────────


async def _fetch_metrics(db: AsyncSession, tenant_id: str | None) -> DashboardMetrics:
    """
    All four metrics in one SQL round-trip.

    Cross-joins two single-row aggregate subqueries so Postgres scans each
    table exactly once. The result is always a single row.

    When tenant_id is None (superadmin), metrics span all tenants.
    """
    order_base = select(
        func.count(Order.id).label("total_orders"),
        func.coalesce(
            func.sum(
                case((Order.state == OrderState.PAID, Order.amount), else_=None)
            ),
            Decimal("0"),
        ).label("total_revenue"),
        func.count(
            case(
                (
                    Order.state.in_(
                        [
                            OrderState.CONFIRMED,
                            OrderState.PAID,
                            OrderState.COMPLETED,
                        ]
                    ),
                    Order.id,
                ),
                else_=None,
            )
        ).label("confirmed_orders"),
    )
    if tenant_id is not None:
        order_base = order_base.where(Order.tenant_id == tenant_id)
    order_sq = order_base.subquery("order_stats")

    conv_base = select(
        func.count(Conversation.id).label("total_conversations"),
        func.count(
            case(
                (
                    Conversation.status == ConversationStatus.ACTIVE,
                    Conversation.id,
                ),
                else_=None,
            )
        ).label("active_conversations"),
    )
    if tenant_id is not None:
        conv_base = conv_base.where(Conversation.tenant_id == tenant_id)
    conv_sq = conv_base.subquery("conv_stats")

    stmt = select(
        order_sq.c.total_orders,
        order_sq.c.total_revenue,
        order_sq.c.confirmed_orders,
        conv_sq.c.total_conversations,
        conv_sq.c.active_conversations,
    ).select_from(order_sq.join(conv_sq, text("true")))

    row = (await db.execute(stmt)).one()

    conversion_rate = (
        round(int(row.confirmed_orders) / int(row.total_conversations), 4)
        if int(row.total_conversations) > 0
        else 0.0
    )

    # ── Debt metrics ────────────────────────────────────────────────────────
    now = datetime.now(tz=timezone.utc)
    debt_filters = [CreditSale.status == CreditSaleStatus.ACTIVE]
    if tenant_id is not None:
        debt_filters.append(CreditSale.tenant_id == tenant_id)

    debt_stmt = select(
        func.count(CreditSale.id).label("active_debts_count"),
        func.coalesce(func.sum(CreditSale.amount), Decimal("0")).label("total_outstanding"),
        func.count(
            case(
                (CreditSale.due_date < now.date(), CreditSale.id),
                else_=None,
            )
        ).label("overdue_debts_count"),
    ).where(*debt_filters)

    debt_row = (await db.execute(debt_stmt)).one()

    return DashboardMetrics(
        total_orders=int(row.total_orders),
        total_revenue=Decimal(str(row.total_revenue)),
        active_conversations=int(row.active_conversations),
        conversion_rate=conversion_rate,
        total_outstanding=Decimal(str(debt_row.total_outstanding)),
        active_debts_count=int(debt_row.active_debts_count),
        overdue_debts_count=int(debt_row.overdue_debts_count),
    )


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.get("/metrics")
async def get_dashboard_metrics(
    user: CurrentUserDep,
    db: DBSessionDep,
) -> DashboardMetrics:
    return await _fetch_metrics(db, _tenant_filter(user))


# ── Recent activity ───────────────────────────────────────────────────────────


class ActivityItem(BaseModel):
    type: str
    content: str
    timestamp: datetime


async def _fetch_recent_activity(
    db: AsyncSession, tenant_id: str | None
) -> list[ActivityItem]:
    """
    UNION ALL of messages / orders / success payments, ordered by timestamp DESC.

    Each branch projects to (type TEXT, content TEXT, timestamp TIMESTAMPTZ) so
    the outer SELECT can ORDER BY and LIMIT without knowing the source table.

    When tenant_id is None (superadmin), activity spans all tenants.
    """
    # Branch 1 — inbound messages only (sender_role = 'user')
    msg_sel = select(
        literal("message").cast(String).label("type"),
        (
            cast(Message.sender_role, String)
            + literal(": ")
            + cast(Message.content, String)
        ).label("content"),
        Message.created_at.label("timestamp"),
    ).where(Message.sender_role == "user")
    if tenant_id is not None:
        msg_sel = msg_sel.where(Message.tenant_id == tenant_id)

    # Branch 2 — order created events
    order_sel = select(
        literal("order").cast(String).label("type"),
        (
            literal("Order created (")
            + cast(func.substr(Order.id, 29, 8), String)
            + literal(")")
        ).label("content"),
        Order.created_at.label("timestamp"),
    )
    if tenant_id is not None:
        order_sel = order_sel.where(Order.tenant_id == tenant_id)

    # Branch 3 — successful payments only
    payment_sel = select(
        literal("payment").cast(String).label("type"),
        (
            literal("Payment successful – ")
            + cast(Payment.amount, String)
            + literal(" ")
            + cast(Payment.currency, String)
        ).label("content"),
        Payment.created_at.label("timestamp"),
    ).where(Payment.status == PaymentStatus.SUCCESS)
    if tenant_id is not None:
        payment_sel = payment_sel.where(Payment.tenant_id == tenant_id)

    combined = union_all(msg_sel, order_sel, payment_sel).subquery("activity")

    stmt = (
        select(
            combined.c.type,
            combined.c.content,
            combined.c.timestamp,
        )
        .order_by(combined.c.timestamp.desc())
        .limit(_ACTIVITY_LIMIT)
    )

    rows = (await db.execute(stmt)).all()
    return [
        ActivityItem(type=row.type, content=row.content, timestamp=row.timestamp)
        for row in rows
    ]


@router.get("/recent-activity")
async def get_recent_activity(
    user: CurrentUserDep,
    db: DBSessionDep,
) -> list[ActivityItem]:
    return await _fetch_recent_activity(db, _tenant_filter(user))


# ── Overview schemas ──────────────────────────────────────────────────────────


class RecentOrder(BaseModel):
    id: str
    state: OrderState
    amount: Decimal | None
    currency: str
    item_count: int
    created_at: datetime


class RecentLastMessage(BaseModel):
    content: str
    timestamp: datetime


class RecentConversation(BaseModel):
    id: str
    customer_identifier: str
    customer_name: str | None
    status: ConversationStatus
    last_message: RecentLastMessage | None
    updated_at: datetime


class RecentPayment(BaseModel):
    id: str
    order_id: str
    reference: str
    amount: Decimal
    currency: str
    status: PaymentStatus
    order_state: OrderState
    order_amount: Decimal | None
    created_at: datetime


class DashboardOverview(BaseModel):
    metrics: DashboardMetrics
    recent_orders: list[RecentOrder]
    recent_conversations: list[RecentConversation]
    recent_payments: list[RecentPayment]


# ── Overview queries ──────────────────────────────────────────────────────────


async def _fetch_recent_orders(db: AsyncSession, tenant_id: str | None) -> list[RecentOrder]:
    """
    Top 5 orders by created_at DESC.

    item_count via correlated scalar subquery — no separate query, no N+1.
    noload() suppresses the default selectin on Order.items.
    """
    item_count_sq = (
        select(func.count(OrderItem.id))
        .where(OrderItem.order_id == Order.id)
        .correlate(Order)
        .scalar_subquery()
    )
    stmt = select(
        Order.id,
        Order.state,
        Order.amount,
        Order.currency,
        item_count_sq.label("item_count"),
        Order.created_at,
    )
    if tenant_id is not None:
        stmt = stmt.where(Order.tenant_id == tenant_id)
    stmt = stmt.order_by(Order.created_at.desc()).limit(_OVERVIEW_LIMIT)
    rows = (await db.execute(stmt)).all()
    return [
        RecentOrder(
            id=row.id,
            state=row.state,
            amount=row.amount,
            currency=row.currency,
            item_count=int(row.item_count),
            created_at=row.created_at,
        )
        for row in rows
    ]


async def _fetch_recent_conversations(
    db: AsyncSession, tenant_id: str | None
) -> list[RecentConversation]:
    """
    Top 5 conversations by updated_at DESC.

    Last message fetched via two correlated scalar subqueries embedded in the
    SELECT list — content and timestamp — so only one query is issued.
    """
    last_msg_content = (
        select(Message.content)
        .where(Message.conversation_id == Conversation.id)
        .order_by(Message.created_at.desc())
        .limit(1)
        .correlate(Conversation)
        .scalar_subquery()
    )
    last_msg_ts = (
        select(Message.created_at)
        .where(Message.conversation_id == Conversation.id)
        .order_by(Message.created_at.desc())
        .limit(1)
        .correlate(Conversation)
        .scalar_subquery()
    )
    stmt = select(
        Conversation.id,
        Conversation.customer_identifier,
        Conversation.customer_name,
        Conversation.status,
        Conversation.updated_at,
        last_msg_content.label("last_content"),
        last_msg_ts.label("last_ts"),
    )
    if tenant_id is not None:
        stmt = stmt.where(Conversation.tenant_id == tenant_id)
    stmt = stmt.order_by(Conversation.updated_at.desc()).limit(_OVERVIEW_LIMIT)
    rows = (await db.execute(stmt)).all()
    return [
        RecentConversation(
            id=row.id,
            customer_identifier=row.customer_identifier,
            customer_name=row.customer_name,
            status=row.status,
            updated_at=row.updated_at,
            last_message=(
                RecentLastMessage(content=row.last_content, timestamp=row.last_ts)
                if row.last_content is not None
                else None
            ),
        )
        for row in rows
    ]


async def _fetch_recent_payments(
    db: AsyncSession, tenant_id: str | None
) -> list[RecentPayment]:
    """
    Top 5 payments by created_at DESC, joined with orders for state + amount.
    """
    stmt = select(
        Payment.id,
        Payment.order_id,
        Payment.reference,
        Payment.amount,
        Payment.currency,
        Payment.status,
        Payment.created_at,
        Order.state.label("order_state"),
        Order.amount.label("order_amount"),
    ).join(Order, Payment.order_id == Order.id)
    if tenant_id is not None:
        stmt = stmt.where(Payment.tenant_id == tenant_id)
    stmt = stmt.order_by(Payment.created_at.desc()).limit(_OVERVIEW_LIMIT)
    rows = (await db.execute(stmt)).all()
    return [
        RecentPayment(
            id=row.id,
            order_id=row.order_id,
            reference=row.reference,
            amount=row.amount,
            currency=row.currency,
            status=row.status,
            created_at=row.created_at,
            order_state=row.order_state,
            order_amount=row.order_amount,
        )
        for row in rows
    ]


# ── Endpoint ──────────────────────────────────────────────────────────────────


# ── Today's Focus ─────────────────────────────────────────────────────────────

_FOCUS_LIMIT = 5
_OVERDUE_HOURS = 24
_WAITING_HOURS = 4
_FOLLOW_UP_HOURS = 12


class TodayFocusItem(BaseModel):
    id: str
    kind: str  # "order" | "conversation"
    urgency: str  # "overdue" | "waiting" | "follow_up"
    title: str
    customer_name: str | None
    conversation_id: str
    since: datetime


class TodayFocusResponse(BaseModel):
    items: list[TodayFocusItem]
    total: int


async def _fetch_today_focus(
    db: AsyncSession, tenant_id: str | None
) -> list[TodayFocusItem]:
    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=_OVERDUE_HOURS)
    cutoff_4h = now - timedelta(hours=_WAITING_HOURS)
    cutoff_12h = now - timedelta(hours=_FOLLOW_UP_HOURS)

    items: list[TodayFocusItem] = []

    # ── 1. Overdue inquiries: inquiry orders untouched for > 24h ──────────────
    overdue_filters = [
        Order.state == OrderState.INQUIRY,
        Order.updated_at < cutoff_24h,
    ]
    if tenant_id is not None:
        overdue_filters.append(Order.tenant_id == tenant_id)
    overdue_stmt = (
        select(
            Order.id,
            Order.conversation_id,
            Order.updated_at,
            Conversation.customer_name,
            Conversation.customer_identifier,
        )
        .join(Conversation, Order.conversation_id == Conversation.id)
        .where(*overdue_filters)
        .order_by(Order.updated_at.asc())
        .limit(_FOCUS_LIMIT)
    )
    for row in (await db.execute(overdue_stmt)).all():
        name = row.customer_name or row.customer_identifier
        items.append(
            TodayFocusItem(
                id=row.id,
                kind="order",
                urgency="overdue",
                title=f"Inquiry from {name} — no update in over {_OVERDUE_HOURS}h",
                customer_name=row.customer_name,
                conversation_id=row.conversation_id,
                since=row.updated_at,
            )
        )

    # ── 2. Unanswered conversations: last message from customer > 4h ago ──────
    last_role_sq = (
        select(Message.sender_role)
        .where(Message.conversation_id == Conversation.id)
        .order_by(Message.created_at.desc())
        .limit(1)
        .correlate(Conversation)
        .scalar_subquery()
    )
    last_ts_sq = (
        select(Message.created_at)
        .where(Message.conversation_id == Conversation.id)
        .order_by(Message.created_at.desc())
        .limit(1)
        .correlate(Conversation)
        .scalar_subquery()
    )
    unanswered_filters = [
        Conversation.status == ConversationStatus.ACTIVE,
        last_role_sq == "user",
        last_ts_sq < cutoff_4h,
    ]
    if tenant_id is not None:
        unanswered_filters.append(Conversation.tenant_id == tenant_id)
    unanswered_stmt = (
        select(
            Conversation.id,
            Conversation.customer_name,
            Conversation.customer_identifier,
            last_ts_sq.label("last_msg_ts"),
        )
        .where(*unanswered_filters)
        .order_by(last_ts_sq.asc())
        .limit(_FOCUS_LIMIT)
    )
    for row in (await db.execute(unanswered_stmt)).all():
        name = row.customer_name or row.customer_identifier
        items.append(
            TodayFocusItem(
                id=row.id,
                kind="conversation",
                urgency="waiting",
                title=f"{name} is waiting — no reply in over {_WAITING_HOURS}h",
                customer_name=row.customer_name,
                conversation_id=row.id,
                since=row.last_msg_ts,
            )
        )

    # ── 3. Confirmed orders with no successful payment for > 12h ──────────────
    no_paid_payment = ~(
        select(Payment.id)
        .where(
            Payment.order_id == Order.id,
            Payment.status == PaymentStatus.SUCCESS,
        )
        .correlate(Order)
        .exists()
    )
    follow_up_filters = [
        Order.state == OrderState.CONFIRMED,
        Order.updated_at < cutoff_12h,
        no_paid_payment,
    ]
    if tenant_id is not None:
        follow_up_filters.append(Order.tenant_id == tenant_id)
    follow_up_stmt = (
        select(
            Order.id,
            Order.conversation_id,
            Order.updated_at,
            Conversation.customer_name,
            Conversation.customer_identifier,
        )
        .join(Conversation, Order.conversation_id == Conversation.id)
        .where(*follow_up_filters)
        .order_by(Order.updated_at.asc())
        .limit(_FOCUS_LIMIT)
    )
    for row in (await db.execute(follow_up_stmt)).all():
        name = row.customer_name or row.customer_identifier
        items.append(
            TodayFocusItem(
                id=row.id,
                kind="order",
                urgency="follow_up",
                title=f"Order confirmed — {name} hasn't paid yet",
                customer_name=row.customer_name,
                conversation_id=row.conversation_id,
                since=row.updated_at,
            )
        )

    # Sort: overdue first → waiting → follow_up; oldest first within each group
    _priority = {"overdue": 0, "waiting": 1, "follow_up": 2}
    items.sort(key=lambda x: (_priority[x.urgency], x.since))
    return items


@router.get("/today-focus")
async def get_today_focus(
    user: CurrentUserDep,
    db: DBSessionDep,
) -> TodayFocusResponse:
    items = await _fetch_today_focus(db, _tenant_filter(user))
    return TodayFocusResponse(items=items, total=len(items))


# ── Overview ──────────────────────────────────────────────────────────────────


@router.get("/overview")
async def get_dashboard_overview(
    user: CurrentUserDep,
    db: DBSessionDep,
) -> DashboardOverview:
    tid = _tenant_filter(user)
    metrics = await _fetch_metrics(db, tid)
    recent_orders = await _fetch_recent_orders(db, tid)
    recent_conversations = await _fetch_recent_conversations(db, tid)
    recent_payments = await _fetch_recent_payments(db, tid)

    return DashboardOverview(
        metrics=metrics,
        recent_orders=recent_orders,
        recent_conversations=recent_conversations,
        recent_payments=recent_payments,
    )
