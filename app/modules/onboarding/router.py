"""
app/modules/onboarding/router.py

Public store endpoint — no authentication required.
Customers and traders visit chattosales.com/store/{slug} which is served
by the Next.js frontend; the frontend fetches trader data from this endpoint.
"""

from urllib.parse import quote

from fastapi import APIRouter, HTTPException

from app.core.config import get_settings
from app.core.dependencies import DBSessionDep
from app.modules.channels.repository import ChannelRepository
from app.modules.onboarding.repository import TraderRepository
from app.modules.onboarding.schemas import TraderStoreOut, normalize_catalogue

router = APIRouter(prefix="/store", tags=["Store"])


def _build_ordering_url(
    *,
    trader_phone: str,
    store_slug: str,
    tenant_id: str | None,
    has_own_channel: bool,
) -> str:
    """
    Return the wa.me URL for the store page's "Order on WhatsApp" button.

    Phase 2 (trader has connected their own WhatsApp Business number):
        wa.me/{trader_phone}  — customers message the trader directly.

    Phase 1 (platform number, no own channel yet):
        wa.me/{platform_number}?text=ORDER:{slug}
        The StoreCatalogue UI extracts the phone number from this URL and
        builds a structured ORDER:{slug}\nItem x2\n... message when the
        customer has selected items.  The ORDER:{slug} prefix alone is the
        fallback for the empty-catalogue button.

    Fallback (platform number not configured):
        wa.me/{trader_phone}  — always functional, even in dev.
    """
    if has_own_channel:
        return f"https://wa.me/{trader_phone}"

    platform_number = get_settings().PLATFORM_WHATSAPP_NUMBER
    if platform_number:
        text = quote(f"ORDER:{store_slug}")
        return f"https://wa.me/{platform_number}?text={text}"

    # Config not set — safe fallback so the button is never broken
    return f"https://wa.me/{trader_phone}"


@router.get("/{slug}", summary="Get public store by slug")
async def get_store(slug: str, db: DBSessionDep) -> TraderStoreOut:
    """
    Return the public profile and catalogue for a trader store.

    This endpoint is intentionally unauthenticated — it is the public-facing
    storefront accessed by customers via the store link sent in the onboarding
    completion message.

    The ordering_whatsapp_url field is computed based on whether the tenant
    has connected their own WhatsApp Business number (Phase 2) or is still
    using the shared platform number (Phase 1).
    """
    repo = TraderRepository(db)
    trader = await repo.get_by_slug(slug)
    if trader is None:
        raise HTTPException(status_code=404, detail="Store not found")

    # Check if the trader's tenant has connected their own WhatsApp channel
    has_own_channel = False
    if trader.tenant_id:
        channel_repo = ChannelRepository(db)
        channel = await channel_repo.get_by_tenant_and_channel(
            tenant_id=trader.tenant_id,
            channel="whatsapp",
        )
        has_own_channel = channel is not None

    ordering_whatsapp_url = _build_ordering_url(
        trader_phone=trader.phone_number,
        store_slug=trader.store_slug or "",
        tenant_id=trader.tenant_id,
        has_own_channel=has_own_channel,
    )

    return TraderStoreOut(
        business_name=trader.business_name or "",
        business_category=trader.business_category or "",
        store_slug=trader.store_slug or "",
        ordering_whatsapp_url=ordering_whatsapp_url,
        catalogue=normalize_catalogue(trader.onboarding_catalogue),
    )
