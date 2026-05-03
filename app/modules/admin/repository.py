"""
app/modules/admin/repository.py

Cross-tenant read-only queries for the superadmin backoffice.

Every method intentionally omits the tenant_id filter so the platform
owner can see all traders, orders, and conversations across the system.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.conversation.models import Conversation
from app.modules.onboarding.models import Trader
from app.modules.orders.models import Order, OrderItem, OrderState

logger = get_logger(__name__)


class AdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Traders ────────────────────────────────────────────────────────────────

    async def list_traders(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Trader], int]:
        """Return all traders ordered by newest first, with total count."""
        data_stmt = (
            select(Trader)
            .order_by(Trader.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        traders = list(
            (await self._session.execute(data_stmt)).scalars().all()
        )
        count_stmt = select(func.count()).select_from(Trader)
        total: int = (await self._session.execute(count_stmt)).scalar_one()
        return traders, total

    async def get_trader_by_phone(self, phone_number: str) -> Trader | None:
        result = await self._session.execute(
            select(Trader).where(Trader.phone_number == phone_number)
        )
        return result.scalar_one_or_none()

    # ── Orders ─────────────────────────────────────────────────────────────────

    async def list_all_orders(
        self,
        *,
        state: str | None = None,
        trader_phone: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Order], int]:
        """Return orders across all tenants, optionally filtered."""
        filters = []
        if state is not None:
            filters.append(Order.state == state)
        if trader_phone is not None:
            filters.append(Order.trader_phone == trader_phone)

        data_stmt = (
            select(Order)
            .where(*filters)
            .order_by(Order.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        orders = list(
            (await self._session.execute(data_stmt)).scalars().all()
        )

        count_stmt = select(func.count()).select_from(Order).where(*filters)
        total: int = (await self._session.execute(count_stmt)).scalar_one()
        return orders, total

    async def get_trader_orders(
        self,
        *,
        trader_phone: str,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Order], int]:
        """Return all orders for a specific trader across all tenants."""
        return await self.list_all_orders(
            trader_phone=trader_phone,
            limit=limit,
            offset=offset,
        )

    # ── Platform metrics ───────────────────────────────────────────────────────

    async def get_platform_metrics(self) -> dict:
        """Aggregate metrics across the entire platform."""
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=today_start.weekday())

        # Total traders
        total_traders: int = (
            await self._session.execute(
                select(func.count()).select_from(Trader)
            )
        ).scalar_one()

        # Total orders + revenue
        order_stats = (
            await self._session.execute(
                select(
                    func.count(Order.id).label("total_orders"),
                    func.coalesce(
                        func.sum(Order.amount), Decimal("0")
                    ).label("total_revenue"),
                )
            )
        ).one()

        # Orders today
        orders_today: int = (
            await self._session.execute(
                select(func.count()).select_from(Order).where(
                    Order.created_at >= today_start
                )
            )
        ).scalar_one()

        # Orders this week
        orders_this_week: int = (
            await self._session.execute(
                select(func.count()).select_from(Order).where(
                    Order.created_at >= week_start
                )
            )
        ).scalar_one()

        # Active conversations
        active_conversations: int = (
            await self._session.execute(
                select(func.count()).select_from(Conversation).where(
                    Conversation.status == "active"
                )
            )
        ).scalar_one()

        return {
            "total_traders": total_traders,
            "total_orders": order_stats.total_orders,
            "total_revenue": order_stats.total_revenue,
            "orders_today": orders_today,
            "orders_this_week": orders_this_week,
            "active_conversations": active_conversations,
        }
