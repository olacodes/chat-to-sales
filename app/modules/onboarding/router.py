"""
app/modules/onboarding/router.py

Public store endpoint + authenticated web onboarding setup.
"""

import json
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, UploadFile, File

from app.core.config import get_settings
from app.core.dependencies import CurrentUserDep, DBSessionDep
from app.core.logging import get_logger
from app.infra.database import async_session_factory
from app.modules.channels.repository import ChannelRepository
from app.modules.onboarding.repository import TraderRepository
from app.modules.onboarding.schemas import (
    CatalogueItem,
    ExtractPricelistResponse,
    StoreListItem,
    StoreListOut,
    TraderStoreOut,
    WebSetupRequest,
    WebSetupResponse,
    normalize_catalogue,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/stores", tags=["Store"])


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


@router.get("", summary="List all public stores")
async def list_stores(db: DBSessionDep) -> StoreListOut:
    """
    Return all completed trader stores for the public directory.

    Unauthenticated — used by the /store listing page.
    Stores are returned newest-first; the frontend groups them by category.
    """
    repo = TraderRepository(db)
    traders = await repo.list_completed(limit=200)

    items = [
        StoreListItem(
            business_name=t.business_name or "",
            business_category=t.business_category or "",
            store_slug=t.store_slug or "",
            item_count=len(normalize_catalogue(t.onboarding_catalogue)),
        )
        for t in traders
        if t.store_slug
    ]

    return StoreListOut(items=items, total=len(items))


@router.get("/catalogue", summary="Get trader's catalogue")
async def get_catalogue(
    user: CurrentUserDep,
    db: DBSessionDep,
) -> list[CatalogueItem]:
    """Return the authenticated trader's product catalogue."""
    from app.core.models.user import User
    from sqlalchemy import select

    db_user = (
        await db.execute(select(User).where(User.id == user.user_id))
    ).scalar_one_or_none()
    phone = db_user.phone_number if db_user else None
    if not phone:
        return []

    repo = TraderRepository(db)
    trader = await repo.get_by_phone(phone)
    if not trader:
        return []

    return normalize_catalogue(trader.onboarding_catalogue)


@router.put("/catalogue", summary="Replace trader's catalogue")
async def update_catalogue(
    body: list[CatalogueItem],
    user: CurrentUserDep,
    db: DBSessionDep,
) -> list[CatalogueItem]:
    """Replace the entire catalogue with the provided products."""
    from app.core.models.user import User
    from sqlalchemy import select
    from app.modules.orders.session import cache_trader_by_phone, get_trader_by_phone_cache

    db_user = (
        await db.execute(select(User).where(User.id == user.user_id))
    ).scalar_one_or_none()
    phone = db_user.phone_number if db_user else None
    if not phone:
        raise HTTPException(status_code=400, detail="Phone number required.")

    catalogue_dict = {item.name: item.price for item in body}

    repo = TraderRepository(db)
    await repo.update_catalogue(phone_number=phone, catalogue=catalogue_dict)
    await db.commit()

    # Bust Redis cache
    cached = await get_trader_by_phone_cache(phone)
    if cached and isinstance(cached, dict) and cached:
        cached["catalogue"] = catalogue_dict
        await cache_trader_by_phone(phone, cached)

    return [CatalogueItem(name=k, price=v) for k, v in catalogue_dict.items()]


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


# ── Web onboarding endpoints (authenticated) ────────────────────────────────


@router.get("/setup/status", summary="Check if current user has completed store setup")
async def get_setup_status(
    user: CurrentUserDep,
    db: DBSessionDep,
) -> dict:
    """Return whether the authenticated user already has a Trader store."""
    from app.core.models.user import User
    from sqlalchemy import select

    db_user = (
        await db.execute(select(User).where(User.id == user.user_id))
    ).scalar_one_or_none()
    phone = db_user.phone_number if db_user else None

    if not phone:
        return {"has_store": False, "store_slug": None}

    repo = TraderRepository(db)
    trader = await repo.get_by_phone(phone)
    if trader and trader.onboarding_status == "complete":
        return {"has_store": True, "store_slug": trader.store_slug}
    return {"has_store": False, "store_slug": None}


@router.post("/setup", summary="Web-based store setup")
async def web_setup(
    body: WebSetupRequest,
    user: CurrentUserDep,
    db: DBSessionDep,
) -> WebSetupResponse:
    """
    Create a Trader store from the web dashboard.

    Requires an authenticated user with a phone number (OTP-verified).
    Creates the Trader row, generates a unique store slug, and caches
    the trader identity so WhatsApp commands work immediately.
    """
    from app.core.models.user import User
    from sqlalchemy import select
    from app.modules.onboarding.service import _generate_unique_slug
    from app.modules.orders.session import cache_trader_by_phone
    from app.modules.onboarding.analytics import (
        EVT_STARTED, EVT_COMPLETED, EVT_PATH_CHOSEN, track_onboarding_event,
    )

    # Get the user's phone number
    db_user = (
        await db.execute(select(User).where(User.id == user.user_id))
    ).scalar_one_or_none()
    if not db_user or not db_user.phone_number:
        raise HTTPException(
            status_code=400,
            detail="Phone number required. Please verify your phone number first.",
        )
    phone = db_user.phone_number

    # Validate
    name = body.business_name.strip()
    if len(name) < 2 or len(name) > 60:
        raise HTTPException(status_code=400, detail="Business name must be 2-60 characters.")

    # Check for existing trader
    repo = TraderRepository(db)
    existing = await repo.get_by_phone(phone)
    if existing and existing.onboarding_status == "complete":
        raise HTTPException(status_code=409, detail="Store already set up.")

    # Build catalogue JSON
    catalogue_dict: dict[str, int] = {}
    if body.products:
        catalogue_dict = {p.name: p.price for p in body.products}
    catalogue_json = json.dumps(catalogue_dict) if catalogue_dict else None

    # Generate slug and create trader
    slug = await _generate_unique_slug(repo, name)
    await repo.create(
        phone_number=phone,
        business_name=name,
        business_category=body.business_category,
        store_slug=slug,
        tenant_id=user.tenant_id,
        onboarding_catalogue=catalogue_json,
    )
    await db.commit()

    # Cache trader identity
    await cache_trader_by_phone(phone, {
        "tenant_id": user.tenant_id,
        "phone_number": phone,
        "business_name": name,
        "business_category": body.business_category,
        "store_slug": slug,
        "catalogue": catalogue_dict,
    })

    # Track analytics
    path = "web_products" if body.products else "web_skip"
    await track_onboarding_event(phone_number=phone, event_type=EVT_STARTED, step_name="web_setup")
    await track_onboarding_event(phone_number=phone, event_type=EVT_PATH_CHOSEN, step_name="catalogue_path", path=path)
    await track_onboarding_event(phone_number=phone, event_type=EVT_COMPLETED, step_name="completed", path=path)

    logger.info("Web onboarding complete phone=%s slug=%s", phone, slug)

    return WebSetupResponse(
        store_slug=slug,
        business_name=name,
        business_category=body.business_category,
        product_count=len(catalogue_dict),
    )


@router.post("/setup/extract-pricelist", summary="Extract products from price list photo")
async def extract_pricelist(
    user: CurrentUserDep,
    file: UploadFile = File(...),
) -> ExtractPricelistResponse:
    """
    Upload a price list photo, run OCR + Claude extraction, return products.

    The frontend can then display the results in an editable table before
    the trader submits the final setup.
    """
    from app.modules.onboarding.media import ocr_image_bytes, extract_products_from_text

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty file.")

    ocr_text = await ocr_image_bytes(image_bytes)
    if not ocr_text:
        return ExtractPricelistResponse(products=[])

    items = await extract_products_from_text(ocr_text, category="")
    products = [CatalogueItem(name=item["name"], price=item["price"]) for item in items]
    return ExtractPricelistResponse(products=products)
