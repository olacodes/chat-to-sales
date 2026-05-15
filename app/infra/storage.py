"""
app/infra/storage.py

Cloudflare R2 (S3-compatible) storage for product images.

Usage:
    from app.infra.storage import upload_product_image, get_image_url

    url = await upload_product_image(
        trader_phone="2348012345678",
        product_name="Indomie Carton",
        image_bytes=b"...",
    )
    # url = "https://images.chattosales.com/products/2348012345678/indomie-carton.jpg"
"""

import hashlib
import re
from io import BytesIO

import boto3
from botocore.config import Config as BotoConfig

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_client = None


def _get_client():
    """Lazy-init the S3 client for R2."""
    global _client
    if _client is not None:
        return _client

    settings = get_settings()
    if not settings.R2_ACCOUNT_ID or not settings.R2_ACCESS_KEY_ID:
        return None

    _client = boto3.client(
        "s3",
        endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        config=BotoConfig(
            signature_version="s3v4",
            retries={"max_attempts": 2, "mode": "standard"},
        ),
        region_name="auto",
    )
    return _client


def _slugify(text: str) -> str:
    """Convert a product name to a URL-safe filename."""
    slug = re.sub(r"\s+", "-", text.lower())
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    return slug.strip("-") or "product"


def _make_key(trader_phone: str, product_name: str) -> str:
    """Generate the R2 object key: products/{phone}/{slug}.jpg"""
    slug = _slugify(product_name)
    return f"products/{trader_phone}/{slug}.jpg"


async def upload_product_image(
    *,
    trader_phone: str,
    product_name: str,
    image_bytes: bytes,
) -> tuple[str | None, str | None]:
    """
    Upload a product image to R2 and return (image_url, image_nobg_url).

    Uploads two versions:
    1. Original JPEG (resized to 800px) — for store page, thumbnails
    2. Transparent PNG (background removed by rembg) — for Status cards

    Returns (None, None) if R2 is not configured.
    """
    from PIL import Image

    client = _get_client()
    if client is None:
        logger.warning("R2 not configured — skipping product image upload")
        return None, None

    settings = get_settings()

    # Resize to max 800px (Status-friendly, small file size)
    try:
        img = Image.open(BytesIO(image_bytes))
        img = img.convert("RGB")
        max_dim = 800
        if img.width > max_dim or img.height > max_dim:
            img.thumbnail((max_dim, max_dim), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        upload_bytes = buf.getvalue()
    except Exception as exc:
        logger.warning("Image resize failed: %s", exc)
        upload_bytes = image_bytes

    # Upload original JPEG
    key = _make_key(trader_phone, product_name)
    try:
        client.put_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=key,
            Body=upload_bytes,
            ContentType="image/jpeg",
        )
    except Exception as exc:
        logger.error("R2 upload failed key=%s: %s", key, exc)
        return None, None

    def _build_url(k: str) -> str:
        if settings.R2_PUBLIC_URL:
            return f"{settings.R2_PUBLIC_URL.rstrip('/')}/{k}"
        return f"https://{settings.R2_BUCKET_NAME}.{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com/{k}"

    image_url = _build_url(key)
    logger.info("Product image uploaded: %s (%d bytes)", key, len(upload_bytes))

    # Upload transparent PNG (background removed)
    nobg_url: str | None = None
    try:
        from app.infra.bg_remove import remove_background
        nobg_bytes = await remove_background(upload_bytes)
        if nobg_bytes:
            nobg_key = f"products/{trader_phone}/{_slugify(product_name)}-nobg.png"
            client.put_object(
                Bucket=settings.R2_BUCKET_NAME,
                Key=nobg_key,
                Body=nobg_bytes,
                ContentType="image/png",
            )
            nobg_url = _build_url(nobg_key)
            logger.info("Product image (no-bg) uploaded: %s (%d bytes)", nobg_key, len(nobg_bytes))
    except Exception as exc:
        logger.warning("Background removal/upload failed (non-fatal): %s", exc)

    return image_url, nobg_url


async def delete_product_image(
    *,
    trader_phone: str,
    product_name: str,
) -> None:
    """Delete a product image from R2."""
    client = _get_client()
    if client is None:
        return

    settings = get_settings()
    key = _make_key(trader_phone, product_name)

    try:
        client.delete_object(Bucket=settings.R2_BUCKET_NAME, Key=key)
        logger.info("Product image deleted: %s", key)
    except Exception as exc:
        logger.warning("R2 delete failed key=%s: %s", key, exc)
