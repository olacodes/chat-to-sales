"""
HTML → Image renderer using Playwright (headless Chromium).

Renders an HTML template string to a 1080x1920 JPEG screenshot.
Falls back to Pillow-based status_kit if Playwright is not installed.
"""

import asyncio
import base64

from app.core.logging import get_logger
from app.infra.templates.base import BaseTemplate, CardContext
from app.infra.templates.schemes import get_scheme

logger = get_logger(__name__)

_VIEWPORT = {"width": 1080, "height": 1920}


async def render_card(
    *,
    template: BaseTemplate,
    ctx: CardContext,
    color_index: int = 0,
) -> bytes | None:
    """
    Render a template to JPEG bytes using Playwright.

    Returns JPEG bytes on success, None if Playwright is unavailable.
    """
    scheme = get_scheme(color_index)
    html = template.html(ctx, scheme)

    try:
        from playwright.async_api import async_playwright
        logger.info("Playwright import OK")
    except ImportError:
        logger.warning("Playwright not installed — falling back to Pillow renderer")
        return None

    try:
        logger.info("Launching Chromium...")
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
            )
            page = await browser.new_page(viewport=_VIEWPORT)
            await page.set_content(html, wait_until="networkidle")
            # Wait a moment for fonts to load
            await page.wait_for_timeout(500)
            screenshot = await page.screenshot(type="jpeg", quality=92)
            await browser.close()

        logger.info(
            "Rendered template=%s scheme=%s size=%d bytes",
            template.name, scheme["name"], len(screenshot),
        )
        return screenshot

    except Exception as exc:
        logger.error("Playwright render failed: %s", exc)
        return None


async def render_status_card(
    *,
    trader_name: str,
    product_name: str,
    price: int,
    store_url: str,
    category: str = "",
    photo_bytes: bytes | None = None,
    color_index: int = 0,
    template_name: str | None = None,
    day_index: int = 0,
    product_index: int = 0,
) -> bytes | None:
    """
    High-level API: render a Status card.

    Picks a template (or uses the specified one), builds context, renders.
    Returns JPEG bytes or None (caller should fall back to Pillow).
    """
    from app.infra.templates import pick_template, pick_random_template, get_template

    # Encode photo as-is (no background removal — works for all photo types)
    photo_b64 = ""
    if photo_bytes:
        photo_b64 = base64.b64encode(photo_bytes).decode("ascii")

    ctx = CardContext(
        trader_name=trader_name,
        product_name=product_name,
        price=price,
        store_url=store_url,
        category=category,
        photo_b64=photo_b64,
    )

    # Pick template
    if template_name:
        tpl = get_template(template_name)
        if tpl is None:
            tpl = pick_template(day_index, product_index)
    else:
        tpl = pick_template(day_index, product_index)

    # Skip text-only templates if no photo and template doesn't support it
    if not ctx.has_photo and not tpl.supports_text_only:
        tpl = pick_template(day_index + 1, product_index)

    return await render_card(template=tpl, ctx=ctx, color_index=color_index)


async def render_random_status_card(
    *,
    trader_name: str,
    product_name: str,
    price: int,
    store_url: str,
    category: str = "",
    photo_bytes: bytes | None = None,
) -> bytes | None:
    """
    Render with random template + color (for on-demand manual generation).
    """
    import random
    from app.infra.templates import pick_random_template

    photo_b64 = ""
    if photo_bytes:
        photo_b64 = base64.b64encode(photo_bytes).decode("ascii")

    ctx = CardContext(
        trader_name=trader_name,
        product_name=product_name,
        price=price,
        store_url=store_url,
        category=category,
        photo_b64=photo_b64,
    )

    tpl = pick_random_template()
    color_index = random.randint(0, 4)

    return await render_card(template=tpl, ctx=ctx, color_index=color_index)
