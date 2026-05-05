"""
app/modules/onboarding/repository.py

Database operations for the Trader model.
"""

import json

from sqlalchemy import select, update
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

    async def list_completed(self, limit: int = 100) -> list[Trader]:
        """Return completed traders with a store slug, ordered by newest first."""
        result = await self._db.execute(
            select(Trader)
            .where(
                Trader.onboarding_status == OnboardingStatus.COMPLETE,
                Trader.store_slug.is_not(None),
            )
            .order_by(Trader.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

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

    async def update_tenant_id(self, *, phone_number: str, tenant_id: str) -> None:
        """Assign a trader-specific tenant_id after their first dashboard login."""
        await self._db.execute(
            update(Trader)
            .where(Trader.phone_number == phone_number)
            .values(tenant_id=tenant_id)
        )

    # ── Catalogue management ────────────────────────────────────────────────

    async def get_catalogue(self, phone_number: str) -> dict[str, int]:
        """Return the trader's catalogue as a {name: price} dict."""
        trader = await self.get_by_phone(phone_number)
        if trader is None or not trader.onboarding_catalogue:
            return {}
        try:
            raw = json.loads(trader.onboarding_catalogue)
            if isinstance(raw, dict):
                return {str(k): int(v) for k, v in raw.items() if v}
            if isinstance(raw, list):
                return {
                    str(item.get("name", "")): int(item.get("price", 0))
                    for item in raw
                    if isinstance(item, dict) and item.get("name") and item.get("price")
                }
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
        return {}

    async def update_category(
        self, *, phone_number: str, category: str
    ) -> None:
        """Update the trader's business category."""
        await self._db.execute(
            update(Trader)
            .where(Trader.phone_number == phone_number)
            .values(business_category=category)
        )

    async def update_catalogue(
        self, *, phone_number: str, catalogue: dict[str, int]
    ) -> None:
        """Persist the updated catalogue dict as JSON."""
        await self._db.execute(
            update(Trader)
            .where(Trader.phone_number == phone_number)
            .values(onboarding_catalogue=json.dumps(catalogue))
        )

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
