"""
app/modules/marketing/customer_list.py

Auto-populates and manages the customer list per trader.
Called after every paid order to keep the list current.
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.marketing.models import CustomerListEntry

logger = get_logger(__name__)


class CustomerListService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def upsert_customer(
        self,
        *,
        trader_phone: str,
        tenant_id: str,
        customer_phone: str,
        customer_name: str | None = None,
        order_amount: Decimal = Decimal("0"),
    ) -> CustomerListEntry:
        """
        Add or update a customer in the trader's customer list.

        Called after every paid order. Updates aggregates.
        """
        result = await self._db.execute(
            select(CustomerListEntry).where(
                CustomerListEntry.trader_phone == trader_phone,
                CustomerListEntry.customer_phone == customer_phone,
            )
        )
        entry = result.scalar_one_or_none()
        now = datetime.now(tz=timezone.utc)

        if entry:
            entry.total_orders += 1
            entry.total_spend += order_amount
            entry.last_order_date = now
            if customer_name and not entry.customer_name:
                entry.customer_name = customer_name
        else:
            entry = CustomerListEntry(
                tenant_id=tenant_id,
                trader_phone=trader_phone,
                customer_phone=customer_phone,
                customer_name=customer_name,
                total_orders=1,
                total_spend=order_amount,
                first_order_date=now,
                last_order_date=now,
            )
            self._db.add(entry)

        await self._db.flush()
        return entry

    async def opt_out(self, trader_phone: str, customer_phone: str) -> bool:
        """
        Mark a customer as opted out. Returns True if found and updated.
        """
        result = await self._db.execute(
            select(CustomerListEntry).where(
                CustomerListEntry.trader_phone == trader_phone,
                CustomerListEntry.customer_phone == customer_phone,
            )
        )
        entry = result.scalar_one_or_none()
        if entry and not entry.opted_out:
            entry.opted_out = True
            entry.opted_out_at = datetime.now(tz=timezone.utc)
            await self._db.flush()
            logger.info("Customer opted out: trader=%s customer=%s", trader_phone, customer_phone)
            return True
        return False

    async def get_customers_for_trader(
        self,
        trader_phone: str,
        *,
        exclude_opted_out: bool = True,
    ) -> list[CustomerListEntry]:
        """Return all customers for a trader."""
        stmt = select(CustomerListEntry).where(
            CustomerListEntry.trader_phone == trader_phone,
        )
        if exclude_opted_out:
            stmt = stmt.where(CustomerListEntry.opted_out == False)  # noqa: E712
        stmt = stmt.order_by(CustomerListEntry.last_order_date.desc())
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def get_customer_count(self, trader_phone: str) -> int:
        """Count active (non-opted-out) customers."""
        from sqlalchemy import func
        result = await self._db.execute(
            select(func.count(CustomerListEntry.id)).where(
                CustomerListEntry.trader_phone == trader_phone,
                CustomerListEntry.opted_out == False,  # noqa: E712
            )
        )
        return result.scalar_one() or 0

    async def get_segment_counts(self, trader_phone: str) -> dict[str, int]:
        """
        Return basic segment counts for a trader.
        Full segment engine (Phase 2) replaces this with computed segments.
        For Phase 1, we use simple order-count based segments.
        """
        customers = await self.get_customers_for_trader(trader_phone)

        counts = {
            "all_customers": 0,
            "vip": 0,           # 5+ orders or N200k+
            "repeat_buyers": 0, # 2-4 orders
            "paid_once": 0,     # 1 order
            "new_leads": 0,     # 0 orders (from conversations)
        }

        for c in customers:
            counts["all_customers"] += 1
            if c.total_orders >= 5 or c.total_spend >= Decimal("200000"):
                counts["vip"] += 1
            elif c.total_orders >= 2:
                counts["repeat_buyers"] += 1
            elif c.total_orders == 1:
                counts["paid_once"] += 1
            else:
                counts["new_leads"] += 1

        return counts

    async def get_customers_by_segment(
        self,
        trader_phone: str,
        segment: str,
    ) -> list[CustomerListEntry]:
        """Return customers matching a basic segment."""
        customers = await self.get_customers_for_trader(trader_phone)

        if segment == "all_customers":
            return customers
        elif segment == "vip":
            return [c for c in customers if c.total_orders >= 5 or c.total_spend >= Decimal("200000")]
        elif segment == "repeat_buyers":
            return [c for c in customers if 2 <= c.total_orders < 5 and c.total_spend < Decimal("200000")]
        elif segment == "paid_once":
            return [c for c in customers if c.total_orders == 1]
        elif segment == "new_leads":
            return [c for c in customers if c.total_orders == 0]
        else:
            return []
