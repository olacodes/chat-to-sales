"""
Base template class for Status Kit cards.

All templates inherit from this. Override `html()` to provide the template.
The renderer calls `html()` → Playwright screenshots → JPEG bytes.
"""

import base64
from dataclasses import dataclass, field


@dataclass
class CardContext:
    """Data passed to every template."""
    trader_name: str
    product_name: str
    price: int
    store_url: str
    category: str = ""
    photo_b64: str = ""  # base64-encoded JPEG (empty = text-only card)

    @property
    def price_formatted(self) -> str:
        return f"N{self.price:,}"

    @property
    def has_photo(self) -> bool:
        return bool(self.photo_b64)

    @property
    def photo_data_uri(self) -> str:
        if self.photo_b64:
            return f"data:image/jpeg;base64,{self.photo_b64}"
        return ""

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
