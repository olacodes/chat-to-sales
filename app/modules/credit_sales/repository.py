"""
app/modules/credit_sales/repository.py
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.credit_sales.models import CreditSale, CreditSaleStatus


class CreditSaleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, credit_sale: CreditSale) -> CreditSale:
        self._session.add(credit_sale)
        await self._session.flush()
        return credit_sale

    async def get_by_id(self, credit_sale_id: str, *, tenant_id: str) -> CreditSale | None:
        result = await self._session.execute(
            select(CreditSale).where(
                CreditSale.id == credit_sale_id,
                CreditSale.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_order_id(self, order_id: str, *, tenant_id: str) -> CreditSale | None:
        result = await self._session.execute(
            select(CreditSale).where(
                CreditSale.order_id == order_id,
                CreditSale.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        tenant_id: str,
        status: CreditSaleStatus | None = None,
    ) -> list[CreditSale]:
        stmt = select(CreditSale).where(CreditSale.tenant_id == tenant_id)
        if status is not None:
            stmt = stmt.where(CreditSale.status == status)
        stmt = stmt.order_by(CreditSale.created_at.desc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def update_status(
        self,
        credit_sale: CreditSale,
        *,
        status: CreditSaleStatus,
    ) -> CreditSale:
        credit_sale.status = status
        await self._session.flush()
        return credit_sale

    async def increment_reminder(self, credit_sale: CreditSale) -> CreditSale:
        credit_sale.reminders_sent += 1
        credit_sale.last_reminded_at = datetime.now(timezone.utc)
        await self._session.flush()
        return credit_sale
