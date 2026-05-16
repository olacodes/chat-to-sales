"""
Base template class for Status Kit cards.

All templates inherit from this. Override `html()` to provide the template.
The renderer calls `html()` → Playwright screenshots → JPEG bytes.
"""

import base64
from dataclasses import dataclass, field
from io import BytesIO


def detect_photo_brightness(photo_b64: str) -> bool:
    """Return True if the photo has a light/bright background. Uses edge sampling."""
    if not photo_b64:
        return False
    try:
        from PIL import Image
        raw = base64.b64decode(photo_b64)
        img = Image.open(BytesIO(raw)).convert("RGB")
        w, h = img.size
        # Sample pixels from all 4 edges
        pixels = []
        for x in range(0, w, max(1, w // 20)):
            pixels.append(img.getpixel((x, 0)))
            pixels.append(img.getpixel((x, h - 1)))
        for y in range(0, h, max(1, h // 20)):
            pixels.append(img.getpixel((0, y)))
            pixels.append(img.getpixel((w - 1, y)))
        avg = sum((r + g + b) / 3 for r, g, b in pixels) / max(len(pixels), 1)
        return avg > 140  # light if edge brightness > 140
    except Exception:
        return False


@dataclass
class CardContext:
    """Data passed to every template."""
    trader_name: str
    product_name: str
    price: int
    store_url: str
    category: str = ""
    photo_b64: str = ""  # base64-encoded JPEG/PNG
    photo_is_light: bool = False  # auto-detected from photo edges

    @property
    def price_formatted(self) -> str:
        return f"N{self.price:,}"

    @property
    def has_photo(self) -> bool:
        return bool(self.photo_b64)

    @property
    def photo_data_uri(self) -> str:
        if not self.photo_b64:
            return ""
        # PNG starts with iVBOR in base64, JPEG with /9j/
        mime = "image/png" if self.photo_b64.startswith("iVBOR") else "image/jpeg"
        return f"data:{mime};base64,{self.photo_b64}"

    @property
    def slug(self) -> str:
        parts = self.store_url.strip("/").split("/")
        return parts[-1] if parts else ""


class BaseTemplate:
    """
    Base class for all Status Kit templates.

    Subclasses must define:
        name: str           — unique template ID (e.g. "maison")
        display_name: str   — human-readable name
    And override:
        html(ctx, scheme) -> str
    """

    name: str = "base"
    display_name: str = "Base"
    supports_text_only: bool = True  # can render without a photo

    def html(self, ctx: CardContext, scheme: dict) -> str:
        """Return a complete HTML document string for rendering."""
        raise NotImplementedError

    def css_vars(self, scheme: dict) -> str:
        """Generate CSS custom property declarations from a color scheme."""
        return "\n".join(
            f"    --{k.replace('_', '-')}: {v};"
            for k, v in scheme.items()
            if k != "name"
        )

    def photo_adaptive_css(self) -> str:
        """CSS classes for light vs dark photo presentation."""
        return """
/* Dark photos: full bleed, no border — photo blends with background */
.photo-dark .product-image {
    width: 100%; height: auto; border-radius: 0;
    filter: drop-shadow(0 30px 50px rgba(0,0,0,.5));
}
/* Light photos: smaller, rounded, with inset shadow frame */
.photo-light .product-image {
    max-width: 85%; max-height: 100%; object-fit: contain;
    border-radius: 12px;
    box-shadow: 0 20px 60px rgba(0,0,0,.7), 0 0 0 1px rgba(255,255,255,.06);
    filter: drop-shadow(0 20px 40px rgba(0,0,0,.6));
}
.photo-light .photo-zone {
    padding: 20px;
}
"""

    def base_styles(self) -> str:
        """Shared CSS reset + Google Fonts import used by all templates."""
        return """
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400;1,500&family=Inter:wght@300;400;500;600&display=swap');
*{margin:0;padding:0;box-sizing:border-box}
body{
  margin:0;padding:0;
  font-family:'Inter',sans-serif;
  width:1080px;height:1920px;
  overflow:hidden;
}
"""
