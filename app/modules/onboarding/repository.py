"""
app/modules/onboarding/repository.py

Database operations for the Trader model.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.onboarding.models import OnboardingStatus, Trader, TraderTier


class TraderRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_by_phone(self, phone_number: str) -> Trader | None:
        result = await self._db.execute(
            select(Trader).where(Trader.phone_number == phone_number)
        )
        return result.scalar_one_or_none()

    async def get_by_tenant(self, tenant_id: str) -> Trader | None:
        """Return the completed trader for a given tenant, or None."""
        result = await self._db.execute(
            select(Trader).where(
                Trader.tenant_id == tenant_id,
                Trader.onboarding_status == OnboardingStatus.COMPLETE,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_slug(self, store_slug: str) -> Trader | None:
        result = await self._db.execute(
            select(Trader).where(Trader.store_slug == store_slug)
        )
        return result.scalar_one_or_none()

    async def slug_exists(self, slug: str) -> bool:
        result = await self._db.execute(
            select(Trader.id).where(Trader.store_slug == slug)
        )
        return result.scalar_one_or_none() is not None

    async def create(
        self,
        *,
        phone_number: str,
        business_name: str,
        business_category: str,
        store_slug: str,
        tenant_id: str | None = None,
        onboarding_catalogue: str | None = None,
    ) -> Trader:
        trader = Trader(
            phone_number=phone_number,
            business_name=business_name,
            business_category=business_category,
            store_slug=store_slug,
            tenant_id=tenant_id,
            onboarding_status=OnboardingStatus.COMPLETE,
            tier=TraderTier.OFE,
            onboarding_catalogue=onboarding_catalogue,
        )
        self._db.add(trader)
        # Caller owns the commit via async_session_factory.begin()
        return trader
