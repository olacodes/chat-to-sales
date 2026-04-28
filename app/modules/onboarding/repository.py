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
        onboarding_catalogue: str | None = None,
    ) -> Trader:
        trader = Trader(
            phone_number=phone_number,
            business_name=business_name,
            business_category=business_category,
            store_slug=store_slug,
            onboarding_status=OnboardingStatus.COMPLETE,
            tier=TraderTier.OFE,
            onboarding_catalogue=onboarding_catalogue,
        )
        self._db.add(trader)
        # Caller owns the commit via async_session_factory.begin()
        return trader
