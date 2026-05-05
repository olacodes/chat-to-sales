"""
app/modules/onboarding/schemas.py

Pydantic schemas for the public store endpoint.
"""

import json
from typing import Any

from pydantic import BaseModel


class CatalogueItem(BaseModel):
    name: str
    price: int


class StoreListItem(BaseModel):
    business_name: str
    business_category: str
    store_slug: str
    item_count: int


class StoreListOut(BaseModel):
    items: list[StoreListItem]
    total: int


class TraderStoreOut(BaseModel):
    business_name: str
    business_category: str
    store_slug: str
    # Full wa.me URL for the "Order on WhatsApp" CTA.
    # Points to the platform number (Phase 1) or the trader's own connected
    # WhatsApp Business number (Phase 2). Computed by the store router.
    ordering_whatsapp_url: str
    catalogue: list[CatalogueItem]


# ── Web onboarding schemas ────────────────────────────────────────────────────


class WebSetupRequest(BaseModel):
    business_name: str
    business_category: str
    products: list[CatalogueItem] = []


class WebSetupResponse(BaseModel):
    store_slug: str
    business_name: str
    business_category: str
    product_count: int


class ExtractPricelistResponse(BaseModel):
    products: list[CatalogueItem]


def normalize_catalogue(raw: str | None) -> list[CatalogueItem]:
    """
    Parse onboarding_catalogue JSON into a uniform list of CatalogueItem.

    Handles all three storage formats produced during onboarding:
    - None / empty  → []                           (Path D: skip)
    - dict          → {"item name": price, ...}    (Path C: Q&A)
    - list          → [{"name": ..., "price": ...}] (Paths A/B: photo/voice)
    """
    if not raw:
        return []
    try:
        parsed: Any = json.loads(raw)
        if isinstance(parsed, list):
            return [
                CatalogueItem(name=str(item["name"]), price=int(item["price"]))
                for item in parsed
            ]
        if isinstance(parsed, dict):
            return [
                CatalogueItem(name=str(k), price=int(v))
                for k, v in parsed.items()
            ]
    except (json.JSONDecodeError, TypeError, KeyError, ValueError):
        pass
    return []
