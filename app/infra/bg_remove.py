"""
app/infra/bg_remove.py

AI-powered product photo background removal using rembg (U2-Net).

Removes the background from a product photo and returns a transparent PNG.
Called at upload time (not render time) so the result is cached in R2.

Falls back gracefully if rembg is not installed.
"""

import asyncio
from io import BytesIO

from app.core.logging import get_logger

logger = get_logger(__name__)

_rembg_available: bool | None = None


def _check_rembg() -> bool:
    """Check if rembg is importable (lazy check, cached)."""
    global _rembg_available
    if _rembg_available is None:
        try:
            import rembg  # noqa: F401
            _rembg_available = True
            logger.info("rembg available — AI background removal enabled")
        except ImportError:
            _rembg_available = False
            logger.warning("rembg not installed — background removal disabled")
    return _rembg_available


def remove_background_sync(image_bytes: bytes) -> bytes | None:
    """
    Remove background from a product photo (synchronous).

    Returns PNG bytes with transparent background, or None on failure.
    The first call downloads the U2-Net model (~170MB) if not cached.
    """
    if not _check_rembg():
        return None

    try:
        from rembg import remove
        from PIL import Image

        # Load and ensure RGB
        img = Image.open(BytesIO(image_bytes)).convert("RGB")

        # Resize if too large (rembg is slow on huge images)
        max_dim = 1024
        if img.width > max_dim or img.height > max_dim:
            img.thumbnail((max_dim, max_dim), Image.LANCZOS)

        # Remove background
        result = remove(img)

        # Save as PNG with alpha
        buf = BytesIO()
        result.save(buf, format="PNG", optimize=True)
        png_bytes = buf.getvalue()

        logger.info(
            "Background removed: input=%dx%d output=%d bytes",
            img.width, img.height, len(png_bytes),
        )
        return png_bytes

    except Exception as exc:
        logger.error("Background removal failed: %s", exc)
        return None


async def remove_background(image_bytes: bytes) -> bytes | None:
    """
    Async wrapper — runs rembg in a thread pool to avoid blocking the event loop.

    Returns PNG bytes with transparent background, or None.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, remove_background_sync, image_bytes)
