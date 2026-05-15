"""
app/infra/status_video_html.py

Generate animated Status videos using HTML templates + Playwright recording.
Replaces the old FFmpeg Ken Burns approach.

Usage:
    video_bytes = await generate_status_video(
        trader_name="Ola", product_name="iPhone 14", price=500000,
        store_url="chattosales.com/stores/ola", photo_bytes=b"...",
    )
"""

import base64
import random

from app.core.logging import get_logger
from app.infra.templates.base import CardContext
from app.infra.templates.schemes import get_scheme

logger = get_logger(__name__)

# Video templates
from app.infra.templates.videos.maison_video import MaisonVideoTemplate
from app.infra.templates.videos.editorial_video import EditorialVideoTemplate
from app.infra.templates.videos.showcase_video import ShowcaseVideoTemplate

_VIDEO_TEMPLATES = [
    MaisonVideoTemplate(),
    EditorialVideoTemplate(),
    ShowcaseVideoTemplate(),
]


async def generate_status_video(
    *,
    trader_name: str,
    product_name: str,
    price: int,
    store_url: str,
    category: str = "",
    photo_bytes: bytes | None = None,
    color_index: int | None = None,
    template_index: int | None = None,
    random_mode: bool = False,
) -> bytes | None:
    """
    Generate an animated Status video.

    Returns MP4 bytes on success, None on failure.
    Falls back to the old FFmpeg Ken Burns if Playwright video fails.
    """
    from app.infra.templates.video_renderer import render_video

    # Build context
    photo_b64 = ""
    if photo_bytes:
        # Try to use nobg version if available
        try:
            from app.infra.bg_remove import remove_background_sync, _check_rembg
            if _check_rembg():
                nobg = remove_background_sync(photo_bytes)
                if nobg:
                    photo_b64 = base64.b64encode(nobg).decode("ascii")
        except Exception:
            pass
        if not photo_b64:
            photo_b64 = base64.b64encode(photo_bytes).decode("ascii")

    ctx = CardContext(
        trader_name=trader_name,
        product_name=product_name,
        price=price,
        store_url=store_url,
        category=category,
        photo_b64=photo_b64,
    )

    # Pick template + color
    if random_mode:
        tpl = random.choice(_VIDEO_TEMPLATES)
        ci = random.randint(0, 4)
    else:
        ti = template_index if template_index is not None else 0
        tpl = _VIDEO_TEMPLATES[ti % len(_VIDEO_TEMPLATES)]
        ci = color_index if color_index is not None else 0

    scheme = get_scheme(ci)
    html = tpl.html(ctx, scheme)

    # Render video
    video_bytes = await render_video(html=html, duration_ms=6000)
    if video_bytes:
        logger.info(
            "Status video generated: template=%s scheme=%s size=%d bytes",
            tpl.name, scheme["name"], len(video_bytes),
        )
        return video_bytes

    # Fallback to old FFmpeg Ken Burns
    logger.warning("HTML video failed, falling back to FFmpeg Ken Burns")
    try:
        from app.infra.status_video import generate_ken_burns_video, EFFECTS
        if photo_bytes:
            return await generate_ken_burns_video(
                photo_bytes=photo_bytes,
                product_name=product_name,
                price=price,
                trader_name=trader_name,
                store_url=store_url,
                effect=random.choice(EFFECTS),
            )
    except Exception as exc:
        logger.warning("FFmpeg fallback also failed: %s", exc)

    return None
