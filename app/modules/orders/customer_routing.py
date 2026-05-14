"""
app/modules/orders/customer_routing.py

Persistent customer → trader routing.

Stores the last trader a customer interacted with so returning customers
are automatically routed even after Redis TTL expires.
"""

from sqlalchemy import String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models.base import BaseModel


class CustomerTraderRouting(BaseModel):
    __tablename__ = "customer_trader_routing"

    customer_phone: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    trader_phone: Mapped[str] = mapped_column(String(40), nullable=False)
    store_slug: Mapped[str] = mapped_column(String(200), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)


class CustomerRoutingRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def upsert(
        self,
        *,
        customer_phone: str,
        trader_phone: str,
        store_slug: str,
        tenant_id: str,
    ) -> None:
        """Save or update the customer→trader routing."""
        result = await self._db.execute(
            select(CustomerTraderRouting).where(
                CustomerTraderRouting.customer_phone == customer_phone
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.trader_phone = trader_phone
            existing.store_slug = store_slug
            existing.tenant_id = tenant_id
        else:
            self._db.add(CustomerTraderRouting(
                customer_phone=customer_phone,
                trader_phone=trader_phone,
                store_slug=store_slug,
                tenant_id=tenant_id,
            ))

    async def get_by_customer(self, customer_phone: str) -> CustomerTraderRouting | None:
        """Return the last trader routing for a customer, or None."""
        result = await self._db.execute(
            select(CustomerTraderRouting).where(
                CustomerTraderRouting.customer_phone == customer_phone
            )
        )
        return result.scalar_one_or_none()
