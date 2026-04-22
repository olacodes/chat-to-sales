"""
app/modules/reports/service.py

WeeklyReportService — aggregates the previous week's data, renders a WhatsApp-
formatted report message, delivers it via NotificationService, and writes an
audit row to weekly_reports.

Week window: Monday 00:00 → Sunday 23:59 (in the tenant's configured timezone).
Idempotency:  a unique index on (tenant_id, week_start) ensures the same week
              is never sent twice even if trigger-weekly is called more than once.

Data gathered (all scoped to the previous calendar week):
  • new_conversations        — conversations started this week
  • new_orders               — orders created (any state)
  • revenue_paid             — sum of PAID order amounts
  • top_customers            — up to 3 customers by order count
  • needs_attention          — open conversations with no agent reply in >24 h
  • WoW delta                — compares new_conversations and revenue to prior week
"""

import uuid
from dataclasses import dataclass, field
from uuid import NAMESPACE_URL
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.conversation.models import Conversation, ConversationStatus, Message
from app.modules.notifications.service import NotificationService
from app.modules.orders.models import Order, OrderState
from app.modules.reports.models import TenantReportConfig, WeeklyReport, WeeklyReportStatus
from app.modules.reports.schemas import ReportConfigUpdate

logger = get_logger(__name__)

_NAIRA = "₦"


# ── Timezone helper ───────────────────────────────────────────────────────────


def _safe_tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        logger.warning("Unknown timezone %r — falling back to Africa/Lagos", name)
        return ZoneInfo("Africa/Lagos")


# ── Date helpers ──────────────────────────────────────────────────────────────


def _get_week_boundaries(
    tz: ZoneInfo,
) -> tuple[datetime, datetime, str]:
    """
    Return (week_start_utc, week_end_utc, week_start_iso) for the *previous*
    ISO week (Mon–Sun) relative to now in the given timezone.
    """
    now_local = datetime.now(tz)
    today = now_local.date()
    # Go back 7 days to land in the previous week, then find that Monday
    prior = today - timedelta(days=7)
    monday = prior - timedelta(days=prior.weekday())  # weekday() == 0 for Monday
    sunday = monday + timedelta(days=6)

    start_local = datetime(monday.year, monday.month, monday.day, 0, 0, 0, tzinfo=tz)
    end_local = datetime(sunday.year, sunday.month, sunday.day, 23, 59, 59, tzinfo=tz)

    return (
        start_local.astimezone(timezone.utc),
        end_local.astimezone(timezone.utc),
        monday.isoformat(),
    )


# ── Aggregation data classes ──────────────────────────────────────────────────


@dataclass
class TopCustomer:
    name: str
    order_count: int
    revenue: Decimal


@dataclass
class NeedsAttention:
    customer_name: str
    customer_identifier: str
    hours_since_last_message: int


@dataclass
class WeeklyMetrics:
    week_start_iso: str
    new_conversations: int
    new_orders: int
    revenue_paid: Decimal
    currency: str
    top_customers: list[TopCustomer] = field(default_factory=list)
    needs_attention: list[NeedsAttention] = field(default_factory=list)
    conv_delta: int = 0
    revenue_delta: Decimal = Decimal("0")


# ── Aggregation queries ────────────────────────────────────────────────────────


async def _gather_metrics(
    db: AsyncSession,
    tenant_id: str,
    week_start: datetime,
    week_end: datetime,
    week_start_iso: str,
) -> WeeklyMetrics:
    """Run all aggregation queries for the given UTC window."""

    # ── 1. New conversations this week ────────────────────────────────────────
    conv_count: int = (
        await db.execute(
            select(func.count(Conversation.id)).where(
                Conversation.tenant_id == tenant_id,
                Conversation.created_at >= week_start,
                Conversation.created_at <= week_end,
            )
        )
    ).scalar_one()

    # ── 2. New orders + revenue paid this week ────────────────────────────────
    order_row = (
        await db.execute(
            select(
                func.count(Order.id).label("order_count"),
                func.coalesce(
                    func.sum(
                        case((Order.state == OrderState.PAID, Order.amount), else_=None)
                    ),
                    Decimal("0"),
                ).label("revenue"),
                func.max(Order.currency).label("currency"),
            ).where(
                Order.tenant_id == tenant_id,
                Order.created_at >= week_start,
                Order.created_at <= week_end,
            )
        )
    ).one()
    new_orders = int(order_row.order_count)
    revenue_paid = Decimal(str(order_row.revenue))
    currency: str = order_row.currency or "NGN"

    # ── 3. Top 3 customers by order count this week ───────────────────────────
    top_rows = (
        await db.execute(
            select(
                Conversation.customer_name,
                Order.customer_id,
                func.count(Order.id).label("order_count"),
                func.coalesce(
                    func.sum(
                        case((Order.state == OrderState.PAID, Order.amount), else_=None)
                    ),
                    Decimal("0"),
                ).label("revenue"),
            )
            .join(Conversation, Order.conversation_id == Conversation.id)
            .where(
                Order.tenant_id == tenant_id,
                Order.created_at >= week_start,
                Order.created_at <= week_end,
            )
            .group_by(Order.customer_id, Conversation.customer_name)
            .order_by(func.count(Order.id).desc())
            .limit(3)
        )
    ).all()
    top_customers = [
        TopCustomer(
            name=row.customer_name or row.customer_id or "Unknown",
            order_count=int(row.order_count),
            revenue=Decimal(str(row.revenue)),
        )
        for row in top_rows
    ]

    # ── 4. Open conversations with no agent reply in >24 h ───────────────────
    # Correlated subqueries to find the last message per conversation
    last_msg_ts_sq = (
        select(Message.created_at)
        .where(Message.conversation_id == Conversation.id)
        .order_by(Message.created_at.desc())
        .limit(1)
        .correlate(Conversation)
        .scalar_subquery()
    )
    last_msg_role_sq = (
        select(Message.sender_role)
        .where(Message.conversation_id == Conversation.id)
        .order_by(Message.created_at.desc())
        .limit(1)
        .correlate(Conversation)
        .scalar_subquery()
    )
    cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)

    attn_rows = (
        await db.execute(
            select(
                Conversation.customer_name,
                Conversation.customer_identifier,
                last_msg_ts_sq.label("last_ts"),
            )
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.status == ConversationStatus.ACTIVE,
                last_msg_role_sq == "user",
                last_msg_ts_sq < cutoff_24h,
            )
            .order_by(last_msg_ts_sq.asc())
            .limit(5)
        )
    ).all()
    needs_attention = []
    now_utc = datetime.now(timezone.utc)
    for row in attn_rows:
        if row.last_ts is None:
            continue
        last_ts = row.last_ts
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
        hours = max(0, int((now_utc - last_ts).total_seconds() // 3600))
        needs_attention.append(
            NeedsAttention(
                customer_name=row.customer_name or row.customer_identifier,
                customer_identifier=row.customer_identifier,
                hours_since_last_message=hours,
            )
        )

    # ── 5. WoW comparison ─────────────────────────────────────────────────────
    prior_start = week_start - timedelta(days=7)
    prior_end = week_end - timedelta(days=7)

    prior_conversations: int = (
        await db.execute(
            select(func.count(Conversation.id)).where(
                Conversation.tenant_id == tenant_id,
                Conversation.created_at >= prior_start,
                Conversation.created_at <= prior_end,
            )
        )
    ).scalar_one()

    prior_revenue = Decimal(
        str(
            (
                await db.execute(
                    select(
                        func.coalesce(
                            func.sum(
                                case(
                                    (Order.state == OrderState.PAID, Order.amount),
                                    else_=None,
                                )
                            ),
                            Decimal("0"),
                        )
                    ).where(
                        Order.tenant_id == tenant_id,
                        Order.created_at >= prior_start,
                        Order.created_at <= prior_end,
                    )
                )
            ).scalar_one()
        )
    )

    return WeeklyMetrics(
        week_start_iso=week_start_iso,
        new_conversations=conv_count,
        new_orders=new_orders,
        revenue_paid=revenue_paid,
        currency=currency,
        top_customers=top_customers,
        needs_attention=needs_attention,
        conv_delta=conv_count - prior_conversations,
        revenue_delta=revenue_paid - prior_revenue,
    )


# ── Message formatter ──────────────────────────────────────────────────────────


def _fmt_delta_int(value: int, label: str) -> str:
    if value > 0:
        return f"+{value} {label}"
    if value < 0:
        return f"{value} {label}"
    return "same as last week"


def _fmt_delta_money(value: Decimal) -> str:
    if value > 0:
        return f"+{_NAIRA}{value:,.0f} vs last week"
    if value < 0:
        return f"-{_NAIRA}{abs(value):,.0f} vs last week"
    return "same as last week"


def render_report(m: WeeklyMetrics) -> str:
    """Render WeeklyMetrics to a WhatsApp-ready text string."""
    from datetime import date as _date

    week_start = _date.fromisoformat(m.week_start_iso)
    week_end = week_start + timedelta(days=6)
    week_label = f"{week_start.strftime('%-d %b')}–{week_end.strftime('%-d %b %Y')}"

    lines: list[str] = [
        f"📊 *Weekly Report* — {week_label}",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "*This week at a glance*",
        f"💬 New leads: *{m.new_conversations}* ({_fmt_delta_int(m.conv_delta, 'vs last week')})",
        f"🛍️ Orders: *{m.new_orders}*",
        f"💰 Revenue (paid): *{_NAIRA}{m.revenue_paid:,.2f}*",
        f"   ↳ {_fmt_delta_money(m.revenue_delta)}",
    ]

    if m.top_customers:
        lines += ["", "━━━━━━━━━━━━━━━━━━━━", "*🏆 Top customers*"]
        for i, c in enumerate(m.top_customers, 1):
            rev = f" — {_NAIRA}{c.revenue:,.0f}" if c.revenue > 0 else ""
            word = "order" if c.order_count == 1 else "orders"
            lines.append(f"{i}. {c.name} ({c.order_count} {word}{rev})")

    if m.needs_attention:
        lines += ["", "━━━━━━━━━━━━━━━━━━━━", "*⚠️ Needs your attention*"]
        for n in m.needs_attention:
            lines.append(f"• {n.customer_name} — waiting {n.hours_since_last_message}h")

    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "_Sent by ChatToSales_",
    ]
    return "\n".join(lines)


# ── Service ────────────────────────────────────────────────────────────────────


class WeeklyReportService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Config CRUD ───────────────────────────────────────────────────────────

    async def get_config(self, tenant_id: str) -> TenantReportConfig:
        """Return the config row, creating a disabled default if none exists."""
        stmt = select(TenantReportConfig).where(
            TenantReportConfig.tenant_id == tenant_id
        )
        config = (await self._db.execute(stmt)).scalar_one_or_none()
        if config is None:
            config = TenantReportConfig(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                enabled=False,
                recipient_phone=None,
                timezone="Africa/Lagos",
            )
            self._db.add(config)
            await self._db.commit()
            await self._db.refresh(config)
        return config

    async def upsert_config(
        self,
        tenant_id: str,
        update: ReportConfigUpdate,
    ) -> TenantReportConfig:
        """Patch the config with only the fields present in the update model."""
        config = await self.get_config(tenant_id)
        if update.enabled is not None:
            config.enabled = update.enabled
        # Use model_fields_set to detect explicit null (clear phone)
        if "recipient_phone" in update.model_fields_set:
            config.recipient_phone = update.recipient_phone
        if update.timezone is not None:
            config.timezone = update.timezone
        await self._db.commit()
        await self._db.refresh(config)
        return config

    # ── Preview ───────────────────────────────────────────────────────────────

    async def send_preview(self, tenant_id: str) -> str:
        """
        Generate the previous week's report and send it immediately as a preview.
        Does not write a WeeklyReport audit row (previews don't count as the
        official weekly send and don't consume idempotency).
        """
        config = await self.get_config(tenant_id)
        if not config.recipient_phone:
            raise ValueError(
                "No recipient_phone configured. Set one via PUT /reports/config."
            )

        tz = _safe_tz(config.timezone)
        week_start, week_end, week_start_iso = _get_week_boundaries(tz)
        metrics = await _gather_metrics(
            self._db, tenant_id, week_start, week_end, week_start_iso
        )
        text = render_report(metrics)

        notification_svc = NotificationService(self._db)
        # Unique event_id per preview call — previews are never deduped
        event_id = f"report.preview.{tenant_id}.{uuid.uuid4()}"
        await notification_svc.send_message(
            tenant_id=tenant_id,
            event_id=event_id,
            recipient=config.recipient_phone,
            message_text=text,
        )
        return text

    # ── Weekly run ────────────────────────────────────────────────────────────

    async def run_weekly(self, tenant_id: str) -> WeeklyReport:
        """
        Send the weekly report for the previous ISO week.

        Idempotent: if a WeeklyReport row already exists for (tenant_id, week_start)
        it is returned immediately without re-sending.
        """
        config = await self.get_config(tenant_id)
        tz = _safe_tz(config.timezone)
        week_start_utc, week_end_utc, week_start_iso = _get_week_boundaries(tz)

        # Idempotency check
        existing = (
            await self._db.execute(
                select(WeeklyReport).where(
                    WeeklyReport.tenant_id == tenant_id,
                    WeeklyReport.week_start == week_start_iso,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            logger.info(
                "Weekly report already exists tenant=%s week=%s status=%s — skipping",
                tenant_id,
                week_start_iso,
                existing.status,
            )
            return existing

        # Skip if report is disabled or recipient is missing
        if not config.enabled or not config.recipient_phone:
            report = WeeklyReport(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                week_start=week_start_iso,
                status=WeeklyReportStatus.SKIPPED,
                recipient_phone=config.recipient_phone,
                error_detail="Report disabled or no recipient configured.",
            )
            self._db.add(report)
            await self._db.commit()
            return report

        try:
            metrics = await _gather_metrics(
                self._db, tenant_id, week_start_utc, week_end_utc, week_start_iso
            )
            text = render_report(metrics)

            notification_svc = NotificationService(self._db)
            # Deterministic UUID so the same (tenant, week) always maps to the
            # same event_id — satisfies the notifications.event_id uniqueness constraint
            # and fits in String(36) without truncation.
            report_event_id = str(
                uuid.uuid5(NAMESPACE_URL, f"report.weekly.{tenant_id}.{week_start_iso}")
            )
            await notification_svc.send_message(
                tenant_id=tenant_id,
                event_id=report_event_id,
                recipient=config.recipient_phone,
                message_text=text,
            )

            report = WeeklyReport(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                week_start=week_start_iso,
                status=WeeklyReportStatus.SENT,
                recipient_phone=config.recipient_phone,
                report_text=text,
            )
            logger.info(
                "Weekly report sent tenant=%s week=%s recipient=%s",
                tenant_id,
                week_start_iso,
                config.recipient_phone,
            )
        except Exception as exc:
            logger.error(
                "Weekly report failed tenant=%s week=%s: %s",
                tenant_id,
                week_start_iso,
                exc,
            )
            report = WeeklyReport(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                week_start=week_start_iso,
                status=WeeklyReportStatus.FAILED,
                recipient_phone=config.recipient_phone,
                error_detail=str(exc)[:500],
            )

        self._db.add(report)
        await self._db.commit()
        return report
