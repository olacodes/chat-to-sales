"""
app/infra/status_kit.py

Generate branded WhatsApp Status images from trader catalogue products.

Two card types:
  1. Photo card — product image as background + dark overlay + text
  2. Text card  — gradient background + text (fallback when no photo)

Output: 1080x1920 JPEG (9:16 vertical, WhatsApp Status optimal)
"""

import io
import math
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.core.logging import get_logger

logger = get_logger(__name__)

_WIDTH = 1080
_HEIGHT = 1920

# Brand colors
_BG_GRADIENT_TOP = (18, 140, 60)       # Dark green
_BG_GRADIENT_BOTTOM = (10, 60, 30)     # Deeper green
_OVERLAY_COLOR = (0, 0, 0, 160)        # Semi-transparent black
_TEXT_WHITE = (255, 255, 255)
_TEXT_LIGHT = (200, 200, 200)
_ACCENT_GREEN = (37, 211, 102)         # WhatsApp green


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a font, trying common system paths then falling back to Pillow default."""
    font_paths = [
        # Linux (Docker)
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        # Alternative Linux paths
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ]
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    # Fallback to Pillow default (limited sizing)
    return ImageFont.load_default()


def _draw_gradient(img: Image.Image) -> None:
    """Draw a vertical green gradient on the image."""
    draw = ImageDraw.Draw(img)
    for y in range(_HEIGHT):
        ratio = y / _HEIGHT
        r = int(_BG_GRADIENT_TOP[0] + (_BG_GRADIENT_BOTTOM[0] - _BG_GRADIENT_TOP[0]) * ratio)
        g = int(_BG_GRADIENT_TOP[1] + (_BG_GRADIENT_BOTTOM[1] - _BG_GRADIENT_TOP[1]) * ratio)
        b = int(_BG_GRADIENT_TOP[2] + (_BG_GRADIENT_BOTTOM[2] - _BG_GRADIENT_TOP[2]) * ratio)
        draw.line([(0, y), (_WIDTH, y)], fill=(r, g, b))


def _draw_text_centered(
    draw: ImageDraw.Draw,
    text: str,
    y: int,
    font: Any,
    fill: tuple,
    max_width: int | None = None,
) -> int:
    """Draw text centered horizontally. Returns the y position after the text."""
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = (_WIDTH - text_width) // 2
    draw.text((x, y), text, font=font, fill=fill)
    return y + text_height


def _naira(amount: int) -> str:
    return f"N{amount:,}"


def generate_text_card(
    *,
    trader_name: str,
    product_name: str,
    price: int,
    store_url: str,
) -> bytes:
    """
    Generate a text-only branded Status card (no product photo).

    Returns JPEG bytes, 1080x1920.
    """
    img = Image.new("RGB", (_WIDTH, _HEIGHT))
    _draw_gradient(img)
    draw = ImageDraw.Draw(img)

    font_trader = _load_font(42, bold=True)
    font_product = _load_font(72, bold=True)
    font_price = _load_font(96, bold=True)
    font_url = _load_font(32)
    font_cta = _load_font(36, bold=True)

    # Trader name (top area)
    y = 600
    y = _draw_text_centered(draw, trader_name.upper(), y, font_trader, _TEXT_LIGHT)

    # Product name
    y += 80
    # Wrap long product names
    words = product_name.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font_product)
        if bbox[2] - bbox[0] > _WIDTH - 120:
            if current:
                lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)

    for line in lines:
        y = _draw_text_centered(draw, line, y, font_product, _TEXT_WHITE)
        y += 10

    # Price
    y += 60
    y = _draw_text_centered(draw, _naira(price), y, font_price, _ACCENT_GREEN)

    # Divider line
    y += 80
    draw.line([(_WIDTH // 4, y), (3 * _WIDTH // 4, y)], fill=_ACCENT_GREEN, width=3)

    # Store URL
    y += 50
    y = _draw_text_centered(draw, store_url, y, font_url, _TEXT_LIGHT)

    # CTA
    y += 30
    y = _draw_text_centered(draw, "Message to order", y, font_cta, _TEXT_WHITE)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def generate_photo_card(
    *,
    trader_name: str,
    product_name: str,
    price: int,
    store_url: str,
    photo_bytes: bytes,
) -> bytes:
    """
    Generate a Status card with the product photo as background.

    Photo is resized to fill 1080x1920, darkened, then text overlaid.
    Returns JPEG bytes.
    """
    # Load and resize photo to fill the canvas
    try:
        photo = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
    except Exception:
        # If photo can't be loaded, fall back to text card
        return generate_text_card(
            trader_name=trader_name,
            product_name=product_name,
            price=price,
            store_url=store_url,
        )

    # Scale to fill (cover) the 1080x1920 canvas
    photo_ratio = photo.width / photo.height
    canvas_ratio = _WIDTH / _HEIGHT
    if photo_ratio > canvas_ratio:
        # Photo is wider — scale by height
        new_height = _HEIGHT
        new_width = int(_HEIGHT * photo_ratio)
    else:
        # Photo is taller — scale by width
        new_width = _WIDTH
        new_height = int(_WIDTH / photo_ratio)
    photo = photo.resize((new_width, new_height), Image.LANCZOS)

    # Center crop
    left = (new_width - _WIDTH) // 2
    top = (new_height - _HEIGHT) // 2
    photo = photo.crop((left, top, left + _WIDTH, top + _HEIGHT))

    # Dark overlay
    overlay = Image.new("RGBA", (_WIDTH, _HEIGHT), _OVERLAY_COLOR)
    img = photo.convert("RGBA")
    img = Image.alpha_composite(img, overlay)
    img = img.convert("RGB")

    draw = ImageDraw.Draw(img)

    font_trader = _load_font(42, bold=True)
    font_product = _load_font(72, bold=True)
    font_price = _load_font(96, bold=True)
    font_url = _load_font(32)
    font_cta = _load_font(36, bold=True)

    # Trader name (top area)
    y = 600
    y = _draw_text_centered(draw, trader_name.upper(), y, font_trader, _TEXT_LIGHT)

    # Product name (wrap long names)
    y += 80
    words = product_name.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font_product)
        if bbox[2] - bbox[0] > _WIDTH - 120:
            if current:
                lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)

    for line in lines:
        y = _draw_text_centered(draw, line, y, font_product, _TEXT_WHITE)
        y += 10

    # Price
    y += 60
    y = _draw_text_centered(draw, _naira(price), y, font_price, _ACCENT_GREEN)

    # Divider
    y += 80
    draw.line([(_WIDTH // 4, y), (3 * _WIDTH // 4, y)], fill=_ACCENT_GREEN, width=3)

    # Store URL
    y += 50
    y = _draw_text_centered(draw, store_url, y, font_url, _TEXT_LIGHT)

    # CTA
    y += 30
    y = _draw_text_centered(draw, "Message to order", y, font_cta, _TEXT_WHITE)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()
