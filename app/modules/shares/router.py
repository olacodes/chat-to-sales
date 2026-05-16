"""
app/modules/shares/router.py

Public endpoint for the share page. No auth needed — the unique ID is the security.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.logging import get_logger
from app.infra.cache import get_redis

logger = get_logger(__name__)

router = APIRouter(prefix="/share", tags=["Share"])

_SHARE_PREFIX = "share:"
_SHARE_TTL = 7 * 24 * 60 * 60  # 7 days


class ShareOut(BaseModel):
    id: str
    media_url: str
    media_type: str  # "image" or "video"
    trader_name: str
    product_name: str
    price: int
    store_url: str


async def create_share(
    *,
    media_url: str,
    media_type: str,
    trader_name: str,
    product_name: str,
    price: int,
    store_url: str,
) -> str:
    """Create a share record in Redis and return the share ID."""
    import json
    share_id = uuid.uuid4().hex[:12]
    data = {
        "id": share_id,
        "media_url": media_url,
        "media_type": media_type,
        "trader_name": trader_name,
        "product_name": product_name,
        "price": price,
        "store_url": store_url,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    redis = get_redis()
    await redis.setex(f"{_SHARE_PREFIX}{share_id}", _SHARE_TTL, json.dumps(data))
    logger.info("Share created: id=%s media_type=%s product=%s", share_id, media_type, product_name)
    return share_id


@router.get("/{share_id}", response_model=ShareOut)
async def get_share(share_id: str) -> ShareOut:
    """Return share metadata for the share page."""
    import json
    redis = get_redis()
    raw = await redis.get(f"{_SHARE_PREFIX}{share_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Share not found or expired")
    data = json.loads(raw)
    return ShareOut(**data)
