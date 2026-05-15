"""
app/infra/status_kit.py

Generate luxury product poster images for WhatsApp Status.

Photo-first design: product photo is the hero (50-70% of card).
3 templates × 4 color schemes = 12 combinations.

Output: 1080x1920 JPEG (9:16 vertical, WhatsApp Status optimal)
"""

import io
import random
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.core.logging import get_logger

logger = get_logger(__name__)

_W = 1080
_H = 1920
_PAD = 60

# ── Color Schemes ────────────────────────────────────────────────────────────

_SCHEMES = [
    {  # Gold Classic
        "bg": (8, 8, 10),
        "accent": (197, 165, 90),
        "text": (240, 237, 230),
        "muted": (120, 115, 105),
        "glow": (197, 165, 90),
    },
    {  # Emerald
        "bg": (6, 14, 10),
        "accent": (37, 211, 102),
        "text": (230, 245, 235),
        "muted": (90, 120, 100),
        "glow": (37, 211, 102),
    },
    {  # Midnight
        "bg": (8, 10, 16),
        "accent": (160, 180, 220),
        "text": (230, 235, 245),
        "muted": (100, 108, 125),
        "glow": (120, 150, 210),
    },
    {  # Rose Gold
        "bg": (12, 8, 8),
        "accent": (210, 145, 115),
        "text": (245, 235, 230),
        "muted": (135, 110, 100),
        "glow": (210, 145, 115),
    },
]


# ── Font + Drawing Helpers ───────────────────────────────────────────────────

def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _naira(amount: int) -> str:
    return f"N{amount:,}"


def _tsize(draw: ImageDraw.Draw, text: str, font: Any) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _center(draw: ImageDraw.Draw, text: str, y: int, font: Any, fill: tuple) -> int:
    tw, th = _tsize(draw, text, font)
    draw.text(((_W - tw) // 2, y), text, font=font, fill=fill)
    return y + th


def _spaced(draw: ImageDraw.Draw, text: str, y: int, font: Any, fill: tuple, spacing: int = 5) -> int:
    chars = list(text.upper())
    total = sum(_tsize(draw, c, font)[0] + spacing for c in chars) - spacing
    x = (_W - total) // 2
    th = 0
    for c in chars:
        cw, th = _tsize(draw, c, font)
        draw.text((x, y), c, font=font, fill=fill)
        x += cw + spacing
    return y + th


def _wrap(draw: ImageDraw.Draw, text: str, font: Any, max_w: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        test = f"{cur} {w}".strip()
        if _tsize(draw, test, font)[0] > max_w and cur:
            lines.append(cur)
            cur = w
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines


def _prep_photo(photo_bytes: bytes, w: int, h: int) -> Image.Image | None:
    try:
        img = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
    except Exception:
        return None
    ratio = img.width / img.height
    target_ratio = w / h
    if ratio > target_ratio:
        nw = int(h * ratio)
        img = img.resize((nw, h), Image.LANCZOS)
        left = (nw - w) // 2
        img = img.crop((left, 0, left + w, h))
    else:
        nh = int(w / ratio)
        img = img.resize((w, nh), Image.LANCZOS)
        top = (nh - h) // 2
        img = img.crop((0, top, w, top + h))
    return img


def _paste_photo(img: Image.Image, photo: Image.Image, x: int, y: int,
                  bg_color: tuple, bottom_fade: int = 50, radius: int = 5,
                  shadow: bool = True) -> None:
    """
    Paste a photo with rounded corners, bottom fade, and drop shadow.

    - Rounded corners (radius px)
    - Bottom edge fades into bg_color (bottom_fade px)
    - Optional drop shadow for depth
    - Left/right/top edges are clean — dark padding handles those
    """
    w, h = photo.size
    photo_rgba = photo.convert("RGBA")

    # Rounded corners mask
    mask = Image.new("L", (w, h), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([0, 0, w, h], radius=radius, fill=255)

    # Bottom fade: gradually reduce alpha at the bottom edge only
    if bottom_fade > 0:
        for i in range(bottom_fade):
            alpha = int(255 * (1 - i / bottom_fade))
            mask_draw.line([(0, h - 1 - i), (w, h - 1 - i)], fill=alpha)

    # Drop shadow
    if shadow:
        shadow_offset = 8
        shadow_blur = 25
        shadow_img = Image.new("RGBA", (w + 60, h + 60), (0, 0, 0, 0))
        shadow_mask = Image.new("L", (w, h), 0)
        sd = ImageDraw.Draw(shadow_mask)
        sd.rounded_rectangle([0, 0, w, h], radius=radius, fill=80)
        shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(radius=shadow_blur))
        shadow_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        shadow_layer.putalpha(shadow_mask)

        img_rgba = img.convert("RGBA")
        img_rgba.paste(shadow_layer, (x + shadow_offset, y + shadow_offset), shadow_layer)
        img.paste(img_rgba.convert("RGB"))

    # Paste the photo with the mask
    canvas = Image.new("RGBA", img.size, (0, 0, 0, 0))
    canvas.paste(photo_rgba, (x, y), mask)
    img_rgba = img.convert("RGBA")
    img_rgba = Image.alpha_composite(img_rgba, canvas)
    img.paste(img_rgba.convert("RGB"))


def _draw_glow(img: Image.Image, cx: int, cy: int, radius: int, color: tuple, intensity: int = 40) -> None:
    """Draw a subtle radial glow behind the product."""
    glow = Image.new("RGBA", (radius * 2, radius * 2), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    for r in range(radius, 0, -2):
        alpha = int(intensity * (r / radius))
        glow_draw.ellipse(
            [radius - r, radius - r, radius + r, radius + r],
            fill=(*color, alpha),
        )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=30))
    # Composite onto image
    img_rgba = img.convert("RGBA")
    img_rgba.paste(glow, (cx - radius, cy - radius), glow)
    img.paste(img_rgba.convert("RGB"))


def _draw_cta(draw: ImageDraw.Draw, y: int, text: str, bg: tuple, fg: tuple) -> int:
    f = _font(26, bold=True)
    tw, th = _tsize(draw, text, f)
    btn_w = tw + 80
    btn_h = th + 32
    x0 = (_W - btn_w) // 2
    draw.rounded_rectangle([x0, y, x0 + btn_w, y + btn_h], radius=btn_h // 2, fill=bg)
    draw.text((x0 + 40, y + 16), text, font=f, fill=fg)
    return y + btn_h


# ══════════════════════════════════════════════════════════════════════════════
# TEMPLATE 1: CENTERED HERO
# Product photo centered with glow, minimal text below
# ══════════════════════════════════════════════════════════════════════════════

def _tpl_centered_photo(img: Image.Image, s: dict, photo: Image.Image,
                        trader: str, product: str, price: int, url: str) -> None:
    draw = ImageDraw.Draw(img)

    # Trader name at top
    y = 60
    _spaced(draw, trader, y, _font(28, bold=True), s["accent"], spacing=6)
    y += 50

    # Subtle glow behind photo area
    _draw_glow(img, _W // 2, 550, 400, s["glow"], intensity=25)
    draw = ImageDraw.Draw(img)  # refresh after glow

    # Product photo — centered with padding, shadow, bottom fade
    photo_w, photo_h = 700, 700
    photo_r = photo.resize((photo_w, photo_h), Image.LANCZOS)
    px = (_W - photo_w) // 2
    py = 220
    _paste_photo(img, photo_r, px, py, s["bg"], bottom_fade=45, radius=5)
    draw = ImageDraw.Draw(img)

    # Product name below photo
    y = py + photo_h + 60
    f_name = _font(56, bold=True)
    lines = _wrap(draw, product, f_name, _W - _PAD * 2)
    for line in lines:
        _center(draw, line, y, f_name, s["text"])
        y += 66

    # Price
    y += 20
    _center(draw, _naira(price), y, _font(72, bold=True), s["accent"])
    y += 100

    # CTA
    y = _draw_cta(draw, y, "MESSAGE TO ORDER  \u2192", s["accent"], s["bg"])
    y += 30

    # Footer
    _center(draw, url, y, _font(22), s["muted"])
    y += 35
    _spaced(draw, f"CURATED BY {trader.upper()}", y, _font(16), s["muted"], spacing=4)


def _tpl_centered_text(img: Image.Image, s: dict,
                       trader: str, product: str, price: int, url: str) -> None:
    draw = ImageDraw.Draw(img)

    # Trader name
    y = 80
    _spaced(draw, trader, y, _font(30, bold=True), s["accent"], spacing=6)
    y += 70

    # Subtle glow
    _draw_glow(img, _W // 2, _H // 2 - 150, 350, s["glow"], intensity=20)
    draw = ImageDraw.Draw(img)

    # Decorative diamond
    _center(draw, "\u25c6", 380, _font(50), s["accent"])

    # Product name — HUGE
    y = 500
    f_name = _font(90, bold=True)
    lines = _wrap(draw, product, f_name, _W - _PAD * 2)
    for line in lines:
        _center(draw, line, y, f_name, s["text"])
        y += 105

    # Price
    y += 50
    _center(draw, _naira(price), y, _font(88, bold=True), s["accent"])
    y += 130

    # CTA
    y = _draw_cta(draw, y, "MESSAGE TO ORDER  \u2192", s["accent"], s["bg"])
    y += 30

    _center(draw, url, y, _font(22), s["muted"])
    y += 35
    _spaced(draw, f"CURATED BY {trader.upper()}", y, _font(16), s["muted"], spacing=4)


# ══════════════════════════════════════════════════════════════════════════════
# TEMPLATE 2: DARK POSTER
# Brand + product name at top, photo centered, price + CTA at bottom
# ══════════════════════════════════════════════════════════════════════════════

def _tpl_poster_photo(img: Image.Image, s: dict, photo: Image.Image,
                      trader: str, product: str, price: int, url: str) -> None:
    draw = ImageDraw.Draw(img)

    # Brand at top
    y = 50
    _spaced(draw, trader, y, _font(26, bold=True), s["accent"], spacing=5)
    y += 45
    _spaced(draw, "NEW COLLECTION", y, _font(18), s["muted"], spacing=4)
    y += 50

    # Product name above photo
    f_name = _font(52, bold=True)
    lines = _wrap(draw, product, f_name, _W - _PAD * 2)
    for line in lines:
        _center(draw, line, y, f_name, s["text"])
        y += 62
    y += 30

    # Glow behind photo
    _draw_glow(img, _W // 2, y + 350, 380, s["glow"], intensity=30)
    draw = ImageDraw.Draw(img)

    # Photo — centered with padding, shadow, bottom fade
    photo_w, photo_h = 720, 650
    photo_r = photo.resize((photo_w, photo_h), Image.LANCZOS)
    px = (_W - photo_w) // 2
    _paste_photo(img, photo_r, px, y, s["bg"], bottom_fade=40, radius=5)
    draw = ImageDraw.Draw(img)
    y += photo_h + 50

    # Price large
    _center(draw, _naira(price), y, _font(76, bold=True), s["accent"])
    y += 110

    # CTA
    y = _draw_cta(draw, y, "ORDER NOW  \u2192", s["accent"], s["bg"])
    y += 30

    # Footer split
    draw.text((_PAD, y), url, font=_font(18), fill=s["muted"])
    slug = url.split("/")[-1] if "/" in url else ""
    if slug:
        sf = _font(18)
        sw, _ = _tsize(draw, slug, sf)
        draw.text((_W - _PAD - sw, y), slug, font=sf, fill=s["muted"])


def _tpl_poster_text(img: Image.Image, s: dict,
                     trader: str, product: str, price: int, url: str) -> None:
    draw = ImageDraw.Draw(img)

    # Brand
    y = 80
    _spaced(draw, trader, y, _font(28, bold=True), s["accent"], spacing=5)
    y += 50
    _spaced(draw, "NEW COLLECTION", y, _font(18), s["muted"], spacing=4)
    y += 80

    # Glow
    _draw_glow(img, _W // 2, _H // 2 - 100, 350, s["glow"], intensity=20)
    draw = ImageDraw.Draw(img)

    # Product name — HUGE hero text
    y = 450
    f_name = _font(100, bold=True)
    lines = _wrap(draw, product, f_name, _W - _PAD * 2)
    for line in lines:
        _center(draw, line, y, f_name, s["text"])
        y += 115
    y += 60

    # Price
    _center(draw, _naira(price), y, _font(88, bold=True), s["accent"])
    y += 140

    # CTA
    y = _draw_cta(draw, y, "ORDER NOW  \u2192", s["accent"], s["bg"])
    y += 30

    _center(draw, url, y, _font(20), s["muted"])


# ══════════════════════════════════════════════════════════════════════════════
# TEMPLATE 3: FULL BLEED
# Photo fills top 65%, fade to dark, text at bottom
# ══════════════════════════════════════════════════════════════════════════════

def _tpl_bleed_photo(img: Image.Image, s: dict, photo: Image.Image,
                     trader: str, product: str, price: int, url: str) -> None:
    # Photo fills top ~55% with bottom fade into dark
    photo_h = int(_H * 0.55)
    photo_w = _W - _PAD * 2
    photo_r = _prep_photo_fill(photo, photo_w, photo_h)
    if photo_r:
        _paste_photo(img, photo_r, _PAD, 30, s["bg"], bottom_fade=80, radius=5, shadow=False)

    # Extra gradient fade for smooth transition
    img_rgba = img.convert("RGBA")
    fade_h = 120
    fade = Image.new("RGBA", (_W, fade_h), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fade)
    for i in range(fade_h):
        alpha = int(255 * (i / fade_h))
        fd.line([(0, i), (_W, i)], fill=(*s["bg"], alpha))
    img_rgba.paste(fade, (0, photo_h - fade_h + 10), fade)
    img.paste(img_rgba.convert("RGB"))

    draw = ImageDraw.Draw(img)

    # Trader name overlaid on photo top
    _spaced(draw, trader, 40, _font(26, bold=True), s["text"], spacing=5)

    # Product name below photo
    y = photo_h + 60
    f_name = _font(58, bold=True)
    lines = _wrap(draw, product, f_name, _W - _PAD * 2)
    for line in lines:
        _center(draw, line, y, f_name, s["text"])
        y += 68
    y += 20

    # Price
    _center(draw, _naira(price), y, _font(78, bold=True), s["accent"])
    y += 110

    # CTA
    y = _draw_cta(draw, y, "MESSAGE TO ORDER  \u2192", s["accent"], s["bg"])
    y += 25

    # Footer
    _center(draw, url, y, _font(20), s["muted"])
    y += 30
    _spaced(draw, f"CURATED BY {trader.upper()}", y, _font(14), s["muted"], spacing=3)


def _tpl_bleed_text(img: Image.Image, s: dict,
                    trader: str, product: str, price: int, url: str) -> None:
    draw = ImageDraw.Draw(img)

    # Trader at top
    y = 80
    _spaced(draw, trader, y, _font(30, bold=True), s["accent"], spacing=6)
    y += 60

    # Accent line
    lw = 120
    draw.line([(_W // 2 - lw, y), (_W // 2 + lw, y)], fill=s["accent"], width=2)
    y += 40

    # Glow
    _draw_glow(img, _W // 2, _H // 2 - 100, 400, s["glow"], intensity=18)
    draw = ImageDraw.Draw(img)

    # Product name centered — very large
    y = 500
    f_name = _font(95, bold=True)
    lines = _wrap(draw, product, f_name, _W - _PAD * 2)
    for line in lines:
        _center(draw, line, y, f_name, s["text"])
        y += 110
    y += 50

    # Accent line
    draw.line([(_W // 2 - lw, y), (_W // 2 + lw, y)], fill=s["accent"], width=2)
    y += 50

    # Price
    _center(draw, _naira(price), y, _font(90, bold=True), s["accent"])
    y += 140

    # CTA
    y = _draw_cta(draw, y, "MESSAGE TO ORDER  \u2192", s["accent"], s["bg"])
    y += 30

    _center(draw, url, y, _font(20), s["muted"])
    y += 30
    _spaced(draw, f"CURATED BY {trader.upper()}", y, _font(14), s["muted"], spacing=3)


# ── Photo fill helper ────────────────────────────────────────────────────────

def _prep_photo_fill(photo: Image.Image, w: int, h: int) -> Image.Image | None:
    """Resize and crop photo to exactly fill w×h."""
    try:
        ratio = photo.width / photo.height
        target_ratio = w / h
        if ratio > target_ratio:
            nw = int(h * ratio)
            photo = photo.resize((nw, h), Image.LANCZOS)
            left = (nw - w) // 2
            return photo.crop((left, 0, left + w, h))
        else:
            nh = int(w / ratio)
            photo = photo.resize((w, nh), Image.LANCZOS)
            top = (nh - h) // 2
            return photo.crop((0, top, w, top + h))
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

_PHOTO_TPLS = [_tpl_centered_photo, _tpl_poster_photo, _tpl_bleed_photo]
_TEXT_TPLS = [_tpl_centered_text, _tpl_poster_text, _tpl_bleed_text]


def generate_photo_card(
    *,
    trader_name: str,
    product_name: str,
    price: int,
    store_url: str,
    photo_bytes: bytes,
    color_index: int = 0,
    template_index: int | None = None,
    product_index: int = 0,
    category: str = "",
) -> bytes:
    s = _SCHEMES[color_index % len(_SCHEMES)]
    tpl_idx = template_index if template_index is not None else (color_index + product_index) % len(_PHOTO_TPLS)

    photo = _prep_photo(photo_bytes, 850, 800)
    if photo is None:
        return generate_text_card(
            trader_name=trader_name, product_name=product_name,
            price=price, store_url=store_url,
            color_index=color_index, product_index=product_index,
        )

    img = Image.new("RGB", (_W, _H), s["bg"])
    _PHOTO_TPLS[tpl_idx % len(_PHOTO_TPLS)](img, s, photo, trader_name, product_name, price, store_url)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def generate_text_card(
    *,
    trader_name: str,
    product_name: str,
    price: int,
    store_url: str,
    color_index: int = 0,
    template_index: int | None = None,
    product_index: int = 0,
    category: str = "",
) -> bytes:
    s = _SCHEMES[color_index % len(_SCHEMES)]
    tpl_idx = template_index if template_index is not None else (color_index + product_index) % len(_TEXT_TPLS)

    img = Image.new("RGB", (_W, _H), s["bg"])
    _TEXT_TPLS[tpl_idx % len(_TEXT_TPLS)](img, s, trader_name, product_name, price, store_url)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()
