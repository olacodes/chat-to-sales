"""
app/infra/status_kit.py

Generate luxury branded WhatsApp Status images from trader catalogue products.

3 templates × 4 color schemes = 12 unique combinations.
Templates: Maison (framed), Editorial (editorial), Showcase (minimal).
Both photo and text card variants for each.

Output: 1080x1920 JPEG (9:16 vertical, WhatsApp Status optimal)
"""

import io
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.core.logging import get_logger

logger = get_logger(__name__)

_W = 1080
_H = 1920
_PAD = 50

# ── Color Schemes ────────────────────────────────────────────────────────────

_SCHEMES = [
    {   # Gold Classic
        "bg": (13, 13, 15),
        "accent": (197, 165, 90),
        "accent_light": (212, 185, 106),
        "text": (240, 237, 230),
        "muted": (138, 133, 120),
        "frame": (42, 38, 32),
        "cta_bg": (197, 165, 90),
        "cta_text": (20, 18, 14),
    },
    {   # Emerald
        "bg": (10, 18, 14),
        "accent": (37, 211, 102),
        "accent_light": (80, 230, 140),
        "text": (230, 245, 235),
        "muted": (110, 140, 120),
        "frame": (30, 50, 38),
        "cta_bg": (37, 211, 102),
        "cta_text": (10, 18, 14),
    },
    {   # Midnight
        "bg": (12, 14, 20),
        "accent": (184, 192, 204),
        "accent_light": (200, 210, 225),
        "text": (230, 235, 245),
        "muted": (120, 126, 140),
        "frame": (35, 38, 50),
        "cta_bg": (184, 192, 204),
        "cta_text": (12, 14, 20),
    },
    {   # Rose Gold
        "bg": (16, 12, 12),
        "accent": (196, 131, 106),
        "accent_light": (220, 160, 135),
        "text": (240, 232, 228),
        "muted": (150, 130, 120),
        "frame": (50, 35, 30),
        "cta_bg": (196, 131, 106),
        "cta_text": (16, 12, 12),
    },
]

# Category display names
_CATEGORY_SUBTITLES = {
    "electronics": "FINE DEVICES",
    "provisions": "QUALITY GOODS",
    "fabric": "TEXTILE COLLECTION",
    "cosmetics": "BEAUTY ESSENTIALS",
    "food": "FRESH PRODUCE",
    "building": "BUILDING MATERIALS",
}

_BADGES = ["AUTHENTIC", "PREMIUM", "VERIFIED", "IN STOCK", "ORIGINAL", "SEALED"]


# ── Font helpers ─────────────────────────────────────────────────────────────

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


# ── Drawing helpers ──────────────────────────────────────────────────────────

def _text_size(draw: ImageDraw.Draw, text: str, font: Any) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _center_text(draw: ImageDraw.Draw, text: str, y: int, font: Any, fill: tuple) -> int:
    tw, th = _text_size(draw, text, font)
    draw.text(((_W - tw) // 2, y), text, font=font, fill=fill)
    return y + th


def _right_text(draw: ImageDraw.Draw, text: str, y: int, font: Any, fill: tuple, margin: int = _PAD) -> int:
    tw, th = _text_size(draw, text, font)
    draw.text((_W - margin - tw, y), text, font=font, fill=fill)
    return y + th


def _draw_spaced(draw: ImageDraw.Draw, text: str, y: int, font: Any, fill: tuple, spacing: int = 6) -> int:
    """Draw letter-spaced uppercase text centered."""
    chars = list(text.upper())
    total_w = 0
    for ch in chars:
        cw, _ = _text_size(draw, ch, font)
        total_w += cw + spacing
    total_w -= spacing
    x = (_W - total_w) // 2
    th = 0
    for ch in chars:
        cw, th = _text_size(draw, ch, font)
        draw.text((x, y), ch, font=font, fill=fill)
        x += cw + spacing
    return y + th


def _wrap_lines(draw: ImageDraw.Draw, text: str, font: Any, max_w: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        test = f"{cur} {w}".strip()
        tw, _ = _text_size(draw, test, font)
        if tw > max_w and cur:
            lines.append(cur)
            cur = w
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines


def _rounded_rect(draw: ImageDraw.Draw, xy: tuple, r: int, fill: tuple | None = None, outline: tuple | None = None, width: int = 1):
    draw.rounded_rectangle(xy, radius=r, fill=fill, outline=outline, width=width)


def _prepare_photo(photo_bytes: bytes, target_w: int, target_h: int) -> Image.Image | None:
    """Load, resize, and crop a photo to fill target dimensions."""
    try:
        photo = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
    except Exception:
        return None
    ratio = photo.width / photo.height
    target_ratio = target_w / target_h
    if ratio > target_ratio:
        new_h = target_h
        new_w = int(target_h * ratio)
    else:
        new_w = target_w
        new_h = int(target_w / ratio)
    photo = photo.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return photo.crop((left, top, left + target_w, top + target_h))


def _pick_scheme(color_index: int) -> dict:
    return _SCHEMES[color_index % len(_SCHEMES)]


def _pick_badge(product_index: int) -> str:
    return _BADGES[product_index % len(_BADGES)]


def _category_subtitle(category: str) -> str:
    return _CATEGORY_SUBTITLES.get(category, "CURATED SELECTION")


# ══════════════════════════════════════════════════════════════════════════════
# TEMPLATE A: MAISON — Framed photo, elegant labels, spec pills
# ══════════════════════════════════════════════════════════════════════════════

def _template_maison_photo(
    draw: ImageDraw.Draw, img: Image.Image, s: dict,
    photo: Image.Image, trader_name: str, product_name: str,
    price: int, store_url: str, category: str, product_index: int,
) -> None:
    # ── Header: brand name + subtitle ──
    y = 40
    _center_text(draw, trader_name, y, _font(44, bold=True), s["text"])
    y += 55
    _draw_spaced(draw, f"{_category_subtitle(category)} \u00b7 EST. 2026", y, _font(20), s["muted"], spacing=4)
    y += 40

    # ── Photo frame ──
    frame_pad = 12
    frame_x = _PAD
    frame_y = y
    frame_w = _W - _PAD * 2
    frame_h = 700
    _rounded_rect(draw, (frame_x, frame_y, frame_x + frame_w, frame_y + frame_h), r=12, outline=s["frame"], width=2)
    # Paste photo inside frame
    photo_resized = photo.resize((frame_w - frame_pad * 2, frame_h - frame_pad * 2), Image.LANCZOS)
    img.paste(photo_resized, (frame_x + frame_pad, frame_y + frame_pad))
    # Refresh draw after paste
    draw = ImageDraw.Draw(img)
    y = frame_y + frame_h + 30

    # ── Diamond ornament ──
    _center_text(draw, "\u25c6", y, _font(16), s["accent"])
    y += 30

    # ── Category label ──
    _draw_spaced(draw, _category_subtitle(category), y, _font(20), s["accent"], spacing=5)
    y += 40

    # ── Product name ──
    f_name = _font(62, bold=True)
    lines = _wrap_lines(draw, product_name, f_name, _W - _PAD * 2)
    for line in lines:
        _center_text(draw, line, y, f_name, s["text"])
        y += 72
    y += 10

    # ── Spec pills ──
    badge = _pick_badge(product_index)
    pills = [badge, f"NO. {product_index + 1:03d}"]
    pill_font = _font(18, bold=True)
    total_pill_w = 0
    pill_data = []
    for label in pills:
        pw, ph = _text_size(draw, label, pill_font)
        pill_data.append((label, pw, ph))
        total_pill_w += pw + 30  # padding
    total_pill_w += 15 * (len(pills) - 1)  # gaps
    px = (_W - total_pill_w) // 2
    for label, pw, ph in pill_data:
        _rounded_rect(draw, (px, y, px + pw + 30, y + ph + 16), r=(ph + 16) // 2, outline=s["muted"], width=1)
        draw.text((px + 15, y + 8), label, font=pill_font, fill=s["muted"])
        px += pw + 30 + 15
    y += 55

    # ── Price section ──
    draw.line([(_PAD, y), (_W - _PAD, y)], fill=s["accent"], width=1)
    y += 20
    draw.text((_PAD + 10, y + 5), "INVESTMENT", font=_font(18), fill=s["muted"])
    draw.text((_PAD + 10, y + 30), "One-time payment", font=_font(16), fill=s["muted"])
    price_text = _naira(price)
    pf = _font(64, bold=True)
    pw, ph = _text_size(draw, price_text, pf)
    draw.text((_W - _PAD - 10 - pw, y), price_text, font=pf, fill=s["accent_light"])
    y += max(ph, 60) + 15
    draw.line([(_PAD, y), (_W - _PAD, y)], fill=s["accent"], width=1)
    y += 30

    # ── CTA button ──
    btn_h = 70
    _rounded_rect(draw, (_PAD, y, _W - _PAD, y + btn_h), r=8, fill=s["cta_bg"])
    cta_text = "MESSAGE TO ORDER  \u2192"
    cf = _font(24, bold=True)
    cw, ch = _text_size(draw, cta_text, cf)
    draw.text(((_W - cw) // 2, y + (btn_h - ch) // 2), cta_text, font=cf, fill=s["cta_text"])
    y += btn_h + 25

    # ── Footer ──
    _draw_spaced(draw, f"OR VISIT {store_url.upper()}", y, _font(16), s["muted"], spacing=3)
    y += 40
    _center_text(draw, "\u25c6", y, _font(12), s["accent"])
    y += 20
    _center_text(draw, f"Curated by {trader_name}", y, _font(22, bold=True), s["accent"])
    y += 30
    _draw_spaced(draw, "AUTHENTIC \u00b7 WARRANTED", y, _font(16), s["muted"], spacing=4)


def _template_maison_text(
    draw: ImageDraw.Draw, img: Image.Image, s: dict,
    trader_name: str, product_name: str,
    price: int, store_url: str, category: str, product_index: int,
) -> None:
    # ── Header ──
    y = 40
    _center_text(draw, trader_name, y, _font(44, bold=True), s["text"])
    y += 55
    _draw_spaced(draw, f"{_category_subtitle(category)} \u00b7 EST. 2026", y, _font(20), s["muted"], spacing=4)
    y += 60

    # ── Decorative frame with large ornament ──
    frame_x, frame_y = _PAD, y
    frame_w, frame_h = _W - _PAD * 2, 650
    _rounded_rect(draw, (frame_x, frame_y, frame_x + frame_w, frame_y + frame_h), r=12, outline=s["frame"], width=2)

    # Large diamond ornament centered in frame
    _center_text(draw, "\u25c6", frame_y + 180, _font(80), s["accent"])

    # Product name inside frame
    f_name = _font(68, bold=True)
    lines = _wrap_lines(draw, product_name, f_name, frame_w - 60)
    name_y = frame_y + 320
    for line in lines:
        _center_text(draw, line, name_y, f_name, s["text"])
        name_y += 80

    y = frame_y + frame_h + 30

    # Same bottom section as photo template
    _center_text(draw, "\u25c6", y, _font(16), s["accent"])
    y += 30
    _draw_spaced(draw, _category_subtitle(category), y, _font(20), s["accent"], spacing=5)
    y += 50

    # Spec pills
    badge = _pick_badge(product_index)
    pills = [badge, f"NO. {product_index + 1:03d}"]
    pill_font = _font(18, bold=True)
    total_pill_w = 0
    pill_data = []
    for label in pills:
        pw, ph = _text_size(draw, label, pill_font)
        pill_data.append((label, pw, ph))
        total_pill_w += pw + 30
    total_pill_w += 15 * (len(pills) - 1)
    px = (_W - total_pill_w) // 2
    for label, pw, ph in pill_data:
        _rounded_rect(draw, (px, y, px + pw + 30, y + ph + 16), r=(ph + 16) // 2, outline=s["muted"], width=1)
        draw.text((px + 15, y + 8), label, font=pill_font, fill=s["muted"])
        px += pw + 30 + 15
    y += 55

    # Price section
    draw.line([(_PAD, y), (_W - _PAD, y)], fill=s["accent"], width=1)
    y += 20
    draw.text((_PAD + 10, y + 5), "INVESTMENT", font=_font(18), fill=s["muted"])
    price_text = _naira(price)
    pf = _font(64, bold=True)
    pw_p, ph_p = _text_size(draw, price_text, pf)
    draw.text((_W - _PAD - 10 - pw_p, y), price_text, font=pf, fill=s["accent_light"])
    y += max(ph_p, 50) + 15
    draw.line([(_PAD, y), (_W - _PAD, y)], fill=s["accent"], width=1)
    y += 30

    # CTA
    btn_h = 70
    _rounded_rect(draw, (_PAD, y, _W - _PAD, y + btn_h), r=8, fill=s["cta_bg"])
    cta_text = "MESSAGE TO ORDER  \u2192"
    cf = _font(24, bold=True)
    cw, ch = _text_size(draw, cta_text, cf)
    draw.text(((_W - cw) // 2, y + (btn_h - ch) // 2), cta_text, font=cf, fill=s["cta_text"])
    y += btn_h + 25

    _draw_spaced(draw, f"OR VISIT {store_url.upper()}", y, _font(16), s["muted"], spacing=3)
    y += 40
    _center_text(draw, f"Curated by {trader_name}", y, _font(22, bold=True), s["accent"])


# ══════════════════════════════════════════════════════════════════════════════
# TEMPLATE B: EDITORIAL — Authentic badge, diamond separator, large price
# ══════════════════════════════════════════════════════════════════════════════

def _template_editorial_photo(
    draw: ImageDraw.Draw, img: Image.Image, s: dict,
    photo: Image.Image, trader_name: str, product_name: str,
    price: int, store_url: str, category: str, product_index: int,
) -> None:
    # ── Header: brand left, badge right ──
    y = 35
    draw.text((_PAD, y), trader_name, font=_font(40, bold=True), fill=s["text"])
    draw.text((_PAD, y + 48), _category_subtitle(category), font=_font(18), fill=s["muted"])

    badge = _pick_badge(product_index)
    badge_f = _font(16, bold=True)
    bw, bh = _text_size(draw, badge, badge_f)
    bx = _W - _PAD - bw - 24
    by = y + 10
    _rounded_rect(draw, (bx, by, bx + bw + 24, by + bh + 14), r=6, outline=s["accent"], width=1)
    draw.text((bx + 12, by + 7), badge, font=badge_f, fill=s["accent"])
    y += 100

    # ── Photo frame ──
    frame_x = _PAD - 5
    frame_w = _W - (_PAD - 5) * 2
    frame_h = 680
    _rounded_rect(draw, (frame_x, y, frame_x + frame_w, y + frame_h), r=10, outline=s["frame"], width=2)
    photo_r = photo.resize((frame_w - 16, frame_h - 16), Image.LANCZOS)
    img.paste(photo_r, (frame_x + 8, y + 8))
    draw = ImageDraw.Draw(img)
    y += frame_h + 25

    # ── Diamond ──
    _center_text(draw, "\u25c6", y, _font(16), s["accent"])
    y += 30

    # ── Spaced category ──
    _draw_spaced(draw, f"{_category_subtitle(category)} \u00b7 UNLOCKED", y, _font(18), s["muted"], spacing=4)
    y += 40

    # ── Product name large ──
    f_name = _font(58, bold=True)
    lines = _wrap_lines(draw, product_name, f_name, _W - _PAD * 2)
    for line in lines:
        _center_text(draw, line, y, f_name, s["text"])
        y += 68
    y += 20

    # ── Gold separator + price ──
    draw.line([(_PAD, y), (_W - _PAD, y)], fill=s["accent"], width=1)
    y += 20
    draw.text((_PAD + 10, y + 8), "Investment", font=_font(22), fill=s["muted"])
    price_text = _naira(price)
    pf = _font(72, bold=True)
    pw, ph = _text_size(draw, price_text, pf)
    draw.text((_W - _PAD - 10 - pw, y - 5), price_text, font=pf, fill=s["accent_light"])
    y += max(ph, 65) + 15
    draw.line([(_PAD, y), (_W - _PAD, y)], fill=s["accent"], width=1)
    y += 35

    # ── CTA ──
    btn_h = 74
    _rounded_rect(draw, (_PAD, y, _W - _PAD, y + btn_h), r=8, fill=s["cta_bg"])
    cf = _font(24, bold=True)
    cta = "MESSAGE TO ORDER  \u2192"
    cw, ch = _text_size(draw, cta, cf)
    draw.text(((_W - cw) // 2, y + (btn_h - ch) // 2), cta, font=cf, fill=s["cta_text"])
    y += btn_h + 20

    # ── Split footer ──
    draw.text((_PAD, y), "CHATTOSALES.COM", font=_font(16), fill=s["muted"])
    slug_part = store_url.split("/")[-1] if "/" in store_url else store_url
    _right_text(draw, f"/STORES/{slug_part.upper()}", y, _font(16), s["muted"])


def _template_editorial_text(
    draw: ImageDraw.Draw, img: Image.Image, s: dict,
    trader_name: str, product_name: str,
    price: int, store_url: str, category: str, product_index: int,
) -> None:
    # Same header
    y = 35
    draw.text((_PAD, y), trader_name, font=_font(40, bold=True), fill=s["text"])
    draw.text((_PAD, y + 48), _category_subtitle(category), font=_font(18), fill=s["muted"])

    badge = _pick_badge(product_index)
    badge_f = _font(16, bold=True)
    bw, bh = _text_size(draw, badge, badge_f)
    bx = _W - _PAD - bw - 24
    by = y + 10
    _rounded_rect(draw, (bx, by, bx + bw + 24, by + bh + 14), r=6, outline=s["accent"], width=1)
    draw.text((bx + 12, by + 7), badge, font=badge_f, fill=s["accent"])
    y += 100

    # ── Decorative frame with product name ──
    frame_x = _PAD - 5
    frame_w = _W - (_PAD - 5) * 2
    frame_h = 680
    _rounded_rect(draw, (frame_x, y, frame_x + frame_w, y + frame_h), r=10, outline=s["frame"], width=2)

    # Large ornament
    _center_text(draw, "\u25c6", y + 200, _font(60), s["accent"])

    # Product name centered in frame
    f_name = _font(64, bold=True)
    lines = _wrap_lines(draw, product_name, f_name, frame_w - 80)
    name_y = y + 330
    for line in lines:
        _center_text(draw, line, name_y, f_name, s["text"])
        name_y += 76

    y += frame_h + 25

    # Diamond + category + price + CTA (same as photo version)
    _center_text(draw, "\u25c6", y, _font(16), s["accent"])
    y += 30
    _draw_spaced(draw, _category_subtitle(category), y, _font(18), s["muted"], spacing=4)
    y += 50

    draw.line([(_PAD, y), (_W - _PAD, y)], fill=s["accent"], width=1)
    y += 20
    draw.text((_PAD + 10, y + 8), "Investment", font=_font(22), fill=s["muted"])
    price_text = _naira(price)
    pf = _font(72, bold=True)
    pw, ph = _text_size(draw, price_text, pf)
    draw.text((_W - _PAD - 10 - pw, y - 5), price_text, font=pf, fill=s["accent_light"])
    y += max(ph, 65) + 15
    draw.line([(_PAD, y), (_W - _PAD, y)], fill=s["accent"], width=1)
    y += 35

    btn_h = 74
    _rounded_rect(draw, (_PAD, y, _W - _PAD, y + btn_h), r=8, fill=s["cta_bg"])
    cf = _font(24, bold=True)
    cta = "MESSAGE TO ORDER  \u2192"
    cw, ch = _text_size(draw, cta, cf)
    draw.text(((_W - cw) // 2, y + (btn_h - ch) // 2), cta, font=cf, fill=s["cta_text"])
    y += btn_h + 20

    draw.text((_PAD, y), "CHATTOSALES.COM", font=_font(16), fill=s["muted"])
    slug_part = store_url.split("/")[-1] if "/" in store_url else store_url
    _right_text(draw, f"/STORES/{slug_part.upper()}", y, _font(16), s["muted"])


# ══════════════════════════════════════════════════════════════════════════════
# TEMPLATE C: SHOWCASE — Full-width photo, product name over bottom edge
# ══════════════════════════════════════════════════════════════════════════════

def _template_showcase_photo(
    draw: ImageDraw.Draw, img: Image.Image, s: dict,
    photo: Image.Image, trader_name: str, product_name: str,
    price: int, store_url: str, category: str, product_index: int,
) -> None:
    # ── Full-width photo top 50% with gold border ──
    photo_h = 950
    photo_r = photo.resize((_W - _PAD * 2, photo_h - 16), Image.LANCZOS)
    img.paste(photo_r, (_PAD + 8, 8))
    draw = ImageDraw.Draw(img)
    _rounded_rect(draw, (_PAD, 0, _W - _PAD, photo_h), r=0, outline=s["accent"], width=2)

    # ── Trader badge top-left on photo ──
    badge_f = _font(22, bold=True)
    bw, bh = _text_size(draw, trader_name.upper(), badge_f)
    _rounded_rect(draw, (_PAD + 15, 15, _PAD + 15 + bw + 24, 15 + bh + 12), r=4, fill=(*s["bg"], 200))
    draw.text((_PAD + 27, 21), trader_name.upper(), font=badge_f, fill=s["accent"])

    # ── Number badge top-right ──
    num_text = f"NO. {product_index + 1:03d}"
    nf = _font(16)
    nw, nh = _text_size(draw, num_text, nf)
    draw.text((_W - _PAD - 20 - nw, 22), num_text, font=nf, fill=s["muted"])

    y = photo_h + 30

    # ── Accent line ──
    draw.line([(_PAD, y), (_W - _PAD, y)], fill=s["accent"], width=2)
    y += 30

    # ── Category ──
    _draw_spaced(draw, _category_subtitle(category), y, _font(18), s["accent"], spacing=5)
    y += 40

    # ── Product name ──
    f_name = _font(64, bold=True)
    lines = _wrap_lines(draw, product_name, f_name, _W - _PAD * 2)
    for line in lines:
        _center_text(draw, line, y, f_name, s["text"])
        y += 74
    y += 15

    # ── Spec pills ──
    badge = _pick_badge(product_index)
    pill_font = _font(17, bold=True)
    bw2, bh2 = _text_size(draw, badge, pill_font)
    bx2 = (_W - bw2 - 24) // 2
    _rounded_rect(draw, (bx2, y, bx2 + bw2 + 24, y + bh2 + 14), r=(bh2 + 14) // 2, outline=s["accent"], width=1)
    draw.text((bx2 + 12, y + 7), badge, font=pill_font, fill=s["accent"])
    y += bh2 + 40

    # ── Price large centered ──
    price_text = _naira(price)
    pf = _font(80, bold=True)
    _center_text(draw, price_text, y, pf, s["accent_light"])
    y += 100

    # ── CTA ──
    btn_h = 70
    _rounded_rect(draw, (_PAD, y, _W - _PAD, y + btn_h), r=8, fill=s["cta_bg"])
    cf = _font(24, bold=True)
    cta = "MESSAGE TO ORDER  \u2192"
    cw, ch = _text_size(draw, cta, cf)
    draw.text(((_W - cw) // 2, y + (btn_h - ch) // 2), cta, font=cf, fill=s["cta_text"])
    y += btn_h + 20

    # ── Footer ──
    _draw_spaced(draw, store_url.upper(), y, _font(16), s["muted"], spacing=3)
    y += 35
    _center_text(draw, f"Curated by {trader_name}", y, _font(20, bold=True), s["accent"])


def _template_showcase_text(
    draw: ImageDraw.Draw, img: Image.Image, s: dict,
    trader_name: str, product_name: str,
    price: int, store_url: str, category: str, product_index: int,
) -> None:
    # ── Top section: brand ──
    y = 60
    _center_text(draw, trader_name.upper(), y, _font(38, bold=True), s["accent"])
    y += 50
    _draw_spaced(draw, _category_subtitle(category), y, _font(18), s["muted"], spacing=4)
    y += 50

    # ── Decorative bordered area ──
    frame_y = y
    frame_h = 750
    _rounded_rect(draw, (_PAD, frame_y, _W - _PAD, frame_y + frame_h), r=10, outline=s["frame"], width=2)

    # Big ornament
    _center_text(draw, "\u25c6", frame_y + 150, _font(100), s["accent"])

    # Product name huge
    f_name = _font(72, bold=True)
    lines = _wrap_lines(draw, product_name, f_name, _W - _PAD * 2 - 60)
    name_y = frame_y + 340
    for line in lines:
        _center_text(draw, line, name_y, f_name, s["text"])
        name_y += 85

    # Badge inside frame
    badge = _pick_badge(product_index)
    pill_font = _font(18, bold=True)
    bw, bh = _text_size(draw, badge, pill_font)
    bx = (_W - bw - 24) // 2
    by = frame_y + frame_h - 60
    _rounded_rect(draw, (bx, by, bx + bw + 24, by + bh + 14), r=(bh + 14) // 2, outline=s["accent"], width=1)
    draw.text((bx + 12, by + 7), badge, font=pill_font, fill=s["accent"])

    y = frame_y + frame_h + 30

    # ── Price ──
    draw.line([(_PAD, y), (_W - _PAD, y)], fill=s["accent"], width=1)
    y += 30
    price_text = _naira(price)
    pf = _font(80, bold=True)
    _center_text(draw, price_text, y, pf, s["accent_light"])
    y += 100
    draw.line([(_PAD, y), (_W - _PAD, y)], fill=s["accent"], width=1)
    y += 30

    # ── CTA ──
    btn_h = 70
    _rounded_rect(draw, (_PAD, y, _W - _PAD, y + btn_h), r=8, fill=s["cta_bg"])
    cf = _font(24, bold=True)
    cta = "MESSAGE TO ORDER  \u2192"
    cw, ch = _text_size(draw, cta, cf)
    draw.text(((_W - cw) // 2, y + (btn_h - ch) // 2), cta, font=cf, fill=s["cta_text"])
    y += btn_h + 20

    _draw_spaced(draw, store_url.upper(), y, _font(16), s["muted"], spacing=3)
    y += 35
    _center_text(draw, f"Curated by {trader_name}", y, _font(20, bold=True), s["accent"])


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

_PHOTO_TEMPLATES = [_template_maison_photo, _template_editorial_photo, _template_showcase_photo]
_TEXT_TEMPLATES = [_template_maison_text, _template_editorial_text, _template_showcase_text]


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
    s = _pick_scheme(color_index)
    tpl_idx = template_index if template_index is not None else (color_index + product_index) % len(_PHOTO_TEMPLATES)

    photo = _prepare_photo(photo_bytes, _W - _PAD * 2, 700)
    if photo is None:
        return generate_text_card(
            trader_name=trader_name, product_name=product_name,
            price=price, store_url=store_url,
            color_index=color_index, product_index=product_index, category=category,
        )

    img = Image.new("RGB", (_W, _H), s["bg"])
    draw = ImageDraw.Draw(img)

    _PHOTO_TEMPLATES[tpl_idx % len(_PHOTO_TEMPLATES)](
        draw, img, s, photo, trader_name, product_name,
        price, store_url, category, product_index,
    )

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=92)
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
    s = _pick_scheme(color_index)
    tpl_idx = template_index if template_index is not None else (color_index + product_index) % len(_TEXT_TEMPLATES)

    img = Image.new("RGB", (_W, _H), s["bg"])
    draw = ImageDraw.Draw(img)

    _TEXT_TEMPLATES[tpl_idx % len(_TEXT_TEMPLATES)](
        draw, img, s, trader_name, product_name,
        price, store_url, category, product_index,
    )

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()
