"""
app/modules/onboarding/router.py

Public store endpoint — no authentication required.
Customers and traders visit chattosales.ng/store/{slug} which is served
by the Next.js frontend; the frontend fetches trader data from this endpoint.
"""

from fastapi import APIRouter, HTTPException

from app.core.dependencies import DBSessionDep
from app.modules.onboarding.repository import TraderRepository
from app.modules.onboarding.schemas import TraderStoreOut, normalize_catalogue

router = APIRouter(prefix="/store", tags=["Store"])


@router.get("/{slug}", summary="Get public store by slug")
async def get_store(slug: str, db: DBSessionDep) -> TraderStoreOut:
    """
    Return the public profile and catalogue for a trader store.

    This endpoint is intentionally unauthenticated — it is the public-facing
    storefront accessed by customers via the store link sent in the onboarding
    completion message.
    """
    repo = TraderRepository(db)
    trader = await repo.get_by_slug(slug)
    if trader is None:
        raise HTTPException(status_code=404, detail="Store not found")
    return TraderStoreOut(
        business_name=trader.business_name or "",
        business_category=trader.business_category or "",
        store_slug=trader.store_slug or "",
        phone_number=trader.phone_number,
        catalogue=normalize_catalogue(trader.onboarding_catalogue),
    )
