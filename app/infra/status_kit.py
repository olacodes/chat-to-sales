"""
app/infra/status_kit.py

Generate branded WhatsApp Status images from trader catalogue products.

Two card types:
  1. Photo card — product photo top 55%, text panel bottom 45%
  2. Text card  — patterned gradient background + zoned text layout

Output: 1080x1920 JPEG (9:16 vertical, WhatsApp Status optimal)
"""

import io
import math
import random
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.core.logging import get_logger

logger = get_logger(__name__)

_WIDTH = 1080
_HEIGHT = 1920
_PADDING = 60

# Brand colors
_TEXT_WHITE = (255, 255, 255)
_TEXT_LIGHT = (200, 210, 200)
_TEXT_MUTED = (150, 160, 150)
_ACCENT_GREEN = (37, 211, 102)       # WhatsApp green
_DARK_BG = (12, 24, 16)             # Near-black green
_PANEL_BG = (16, 32, 22)            # Slightly lighter panel

# Color schemes for variety
_COLOR_SCHEMES = [
    {"top": (18, 100, 50), "bottom": (8, 40, 22), "accent": (37, 211, 102)},   # Green
    {"top": (20, 40, 90), "bottom": (10, 18, 50), "accent": (80, 160, 255)},   # Blue
    {"top": (60, 20, 80), "bottom": (30, 10, 45), "accent": (180, 120, 255)},  # Purple
    {"top": (30, 30, 35), "bottom": (12, 12, 14), "accent": (37, 211, 102)},   # Dark
]


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ]
    for path in font_paths:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _naira(amount: int) -> str:
    return f"N{amount:,}"


def _draw_gradient(draw: ImageDraw.Draw, y_start: int, y_end: int, color_top: tuple, color_bottom: tuple) -> None:
    """Draw a vertical gradient between two colors in a region."""
    height = y_end - y_start
    for y in range(y_start, y_end):
        ratio = (y - y_start) / max(height, 1)
        r = int(color_top[0] + (color_bottom[0] - color_top[0]) * ratio)
        g = int(color_top[1] + (color_bottom[1] - color_top[1]) * ratio)
        b = int(color_top[2] + (color_bottom[2] - color_top[2]) * ratio)
        draw.line([(0, y), (_WIDTH, y)], fill=(r, g, b))


def _draw_dot_pattern(draw: ImageDraw.Draw, y_start: int, y_end: int, color: tuple, spacing: int = 40) -> None:
    """Draw a subtle dot grid pattern for texture."""
    dot_color = (color[0], color[1], color[2], 30)
    for y in range(y_start, y_end, spacing):
        for x in range(0, _WIDTH, spacing):
            draw.ellipse([x - 1, y - 1, x + 1, y + 1], fill=color)


def _draw_text_centered(draw: ImageDraw.Draw, text: str, y: int, font: Any, fill: tuple) -> int:
    """Draw text centered horizontally. Returns y after text."""
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(((_WIDTH - tw) // 2, y), text, font=font, fill=fill)
    return y + th


def _wrap_text(draw: ImageDraw.Draw, text: str, font: Any, max_width: int) -> list[str]:
    """Word-wrap text to fit within max_width."""
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] > max_width:
            if current:
                lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)
    return lines


def _draw_rounded_rect(draw: ImageDraw.Draw, xy: tuple, radius: int, fill: tuple) -> None:
    """Draw a rounded rectangle."""
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill)


def _draw_price_badge(draw: ImageDraw.Draw, price_text: str, center_y: int, accent: tuple) -> int:
    """Draw a pill-shaped price badge centered horizontally. Returns y after badge."""
    font = _load_font(88, bold=True)
    bbox = draw.textbbox((0, 0), price_text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    pad_x, pad_y = 50, 20
    badge_w = tw + pad_x * 2
    badge_h = th + pad_y * 2
    x0 = (_WIDTH - badge_w) // 2
    y0 = center_y - pad_y

    _draw_rounded_rect(draw, (x0, y0, x0 + badge_w, y0 + badge_h), radius=badge_h // 2, fill=accent)
    draw.text((x0 + pad_x, y0 + pad_y), price_text, font=font, fill=_TEXT_WHITE)
    return y0 + badge_h


def _draw_cta_button(draw: ImageDraw.Draw, text: str, center_y: int) -> int:
    """Draw a CTA button look."""
    font = _load_font(34, bold=True)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    pad_x, pad_y = 40, 16
    btn_w = tw + pad_x * 2
    btn_h = th + pad_y * 2
    x0 = (_WIDTH - btn_w) // 2
    y0 = center_y

    # Border only (outline button)
    draw.rounded_rectangle(
        [x0, y0, x0 + btn_w, y0 + btn_h],
        radius=btn_h // 2,
        outline=_TEXT_WHITE,
        width=2,
    )
    draw.text((x0 + pad_x, y0 + pad_y), text, font=font, fill=_TEXT_WHITE)
    return y0 + btn_h


# ─── Text Card ────────────────────────────────────────────────────────────────


def generate_text_card(
    *,
    trader_name: str,
    product_name: str,
    price: int,
    store_url: str,
    color_index: int = 0,
) -> bytes:
    """
    Generate a text-only branded Status card.

    Professional layout with gradient, dot pattern, zoned text, price badge, CTA button.
    """
    scheme = _COLOR_SCHEMES[color_index % len(_COLOR_SCHEMES)]
    accent = scheme["accent"]

    img = Image.new("RGBA", (_WIDTH, _HEIGHT), _DARK_BG)
    draw = ImageDraw.Draw(img)

    # Background gradient
    _draw_gradient(draw, 0, _HEIGHT, scheme["top"], scheme["bottom"])

    # Subtle dot pattern for texture
    dot_color = (
        min(scheme["top"][0] + 15, 255),
        min(scheme["top"][1] + 15, 255),
        min(scheme["top"][2] + 15, 255),
    )
    _draw_dot_pattern(draw, 0, _HEIGHT, dot_color, spacing=50)

    # ── Top bar: trader name ──────────────────────────────────────────────
    # Semi-transparent bar
    bar_h = 120
    bar_overlay = Image.new("RGBA", (_WIDTH, bar_h), (0, 0, 0, 80))
    img.paste(bar_overlay, (0, 0), bar_overlay)
    draw = ImageDraw.Draw(img)  # refresh after paste

    font_trader = _load_font(36, bold=True)
    _draw_text_centered(draw, trader_name.upper(), 40, font_trader, _TEXT_LIGHT)

    # ── Accent line under header ──────────────────────────────────────────
    draw.line([(0, bar_h), (_WIDTH, bar_h)], fill=(*accent, 120), width=3)

    # ── Hero zone: product name (BIG) ─────────────────────────────────────
    font_product = _load_font(82, bold=True)
    lines = _wrap_text(draw, product_name, font_product, _WIDTH - _PADDING * 2)

    # Center the product text block vertically in the hero zone
    line_height = 95
    total_text_h = len(lines) * line_height
    hero_y_start = 500 - total_text_h // 2

    for i, line in enumerate(lines):
        _draw_text_centered(draw, line, hero_y_start + i * line_height, font_product, _TEXT_WHITE)

    # ── Decorative accent lines ───────────────────────────────────────────
    accent_y = hero_y_start - 50
    line_w = 80
    draw.line([(_WIDTH // 2 - line_w, accent_y), (_WIDTH // 2 + line_w, accent_y)], fill=accent, width=4)

    # ── Price badge ───────────────────────────────────────────────────────
    price_y = hero_y_start + total_text_h + 80
    badge_bottom = _draw_price_badge(draw, _naira(price), price_y, accent)

    # ── Bottom panel ──────────────────────────────────────────────────────
    panel_y = _HEIGHT - 380
    panel_overlay = Image.new("RGBA", (_WIDTH, 380), (0, 0, 0, 120))
    img.paste(panel_overlay, (0, panel_y), panel_overlay)
    draw = ImageDraw.Draw(img)

    # Accent line above panel
    draw.line([(0, panel_y), (_WIDTH, panel_y)], fill=(*accent, 100), width=2)

    # CTA button
    _draw_cta_button(draw, "Message to order", panel_y + 60)

    # Store URL
    font_url = _load_font(28)
    _draw_text_centered(draw, store_url, panel_y + 180, font_url, _TEXT_MUTED)

    # Small "ChatToSales" branding
    font_brand = _load_font(22)
    _draw_text_centered(draw, "Powered by ChatToSales", panel_y + 280, font_brand, (*_TEXT_MUTED[:3],))

    # Convert to RGB for JPEG
    img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


# ─── Photo Card ───────────────────────────────────────────────────────────────


def generate_photo_card(
    *,
    trader_name: str,
    product_name: str,
    price: int,
    store_url: str,
    photo_bytes: bytes,
    color_index: int = 0,
) -> bytes:
    """
    Generate a Status card with product photo top 55% + text panel bottom 45%.

    Photo is clearly visible. Text is on a solid dark panel — no transparency issues.
    """
    scheme = _COLOR_SCHEMES[color_index % len(_COLOR_SCHEMES)]
    accent = scheme["accent"]

    try:
        photo = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
    except Exception:
        return generate_text_card(
            trader_name=trader_name,
            product_name=product_name,
            price=price,
            store_url=store_url,
            color_index=color_index,
        )

    img = Image.new("RGB", (_WIDTH, _HEIGHT), _DARK_BG)

    # ── Photo zone: top 55% ───────────────────────────────────────────────
    photo_h = int(_HEIGHT * 0.55)

    # Scale photo to fill the photo zone
    photo_ratio = photo.width / photo.height
    zone_ratio = _WIDTH / photo_h
    if photo_ratio > zone_ratio:
        new_height = photo_h
        new_width = int(photo_h * photo_ratio)
    else:
        new_width = _WIDTH
        new_height = int(_WIDTH / photo_ratio)

    photo = photo.resize((new_width, new_height), Image.LANCZOS)
    left = (new_width - _WIDTH) // 2
    top = (new_height - photo_h) // 2
    photo = photo.crop((left, top, left + _WIDTH, top + photo_h))

    img.paste(photo, (0, 0))

    # Gradient fade at the bottom of the photo into the dark panel
    fade_h = 120
    for i in range(fade_h):
        alpha = int(255 * (i / fade_h))
        y = photo_h - fade_h + i
        draw_temp = ImageDraw.Draw(img)
        draw_temp.line(
            [(0, y), (_WIDTH, y)],
            fill=(
                _DARK_BG[0],
                _DARK_BG[1],
                _DARK_BG[2],
            ),
        )
    # Re-paste the photo with RGBA fade
    img_rgba = img.convert("RGBA")
    fade_overlay = Image.new("RGBA", (_WIDTH, fade_h), (0, 0, 0, 0))
    fade_draw = ImageDraw.Draw(fade_overlay)
    for i in range(fade_h):
        alpha = int(255 * (i / fade_h))
        fade_draw.line([(0, i), (_WIDTH, i)], fill=(*_DARK_BG, alpha))
    img_rgba.paste(fade_overlay, (0, photo_h - fade_h), fade_overlay)

    # ── Trader name badge on the photo (top-left) ─────────────────────────
    draw = ImageDraw.Draw(img_rgba)
    font_trader = _load_font(32, bold=True)
    trader_text = trader_name.upper()
    bbox = draw.textbbox((0, 0), trader_text, font=font_trader)
    tw = bbox[2] - bbox[0]

    # Semi-transparent pill behind trader name
    pill_x = _PADDING
    pill_y = 50
    pill_w = tw + 40
    pill_h = 50
    pill_overlay = Image.new("RGBA", (pill_w, pill_h), (0, 0, 0, 140))
    pill_draw = ImageDraw.Draw(pill_overlay)
    pill_draw.rounded_rectangle([0, 0, pill_w, pill_h], radius=25, fill=(0, 0, 0, 140))
    img_rgba.paste(pill_overlay, (pill_x, pill_y), pill_overlay)
    draw = ImageDraw.Draw(img_rgba)
    draw.text((pill_x + 20, pill_y + 10), trader_text, font=font_trader, fill=_TEXT_WHITE)

    # ── Text panel: bottom 45% ────────────────────────────────────────────
    panel_y = photo_h - 40  # slight overlap for seamless look

    # Panel gradient
    _draw_gradient(draw, panel_y + 40, _HEIGHT, scheme["bottom"], _DARK_BG)

    # Product name
    font_product = _load_font(68, bold=True)
    lines = _wrap_text(draw, product_name, font_product, _WIDTH - _PADDING * 2)
    y = panel_y + 80
    line_h = 80
    for line in lines:
        _draw_text_centered(draw, line, y, font_product, _TEXT_WHITE)
        y += line_h

    # Price badge
    y += 40
    badge_bottom = _draw_price_badge(draw, _naira(price), y, accent)

    # CTA button
    cta_y = badge_bottom + 60
    _draw_cta_button(draw, "Message to order", cta_y)

    # Store URL
    font_url = _load_font(26)
    _draw_text_centered(draw, store_url, cta_y + 90, font_url, _TEXT_MUTED)

    # Branding
    font_brand = _load_font(20)
    _draw_text_centered(draw, "Powered by ChatToSales", _HEIGHT - 60, font_brand, _TEXT_MUTED)

    # Convert to RGB for JPEG
    img = img_rgba.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()
