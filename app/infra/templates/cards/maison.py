"""
Template: Maison — Centered hero, luxury serif branding, radial glow.
"""

from app.infra.templates.base import BaseTemplate, CardContext


class MaisonTemplate(BaseTemplate):
    name = "maison"
    display_name = "Maison"

    def html(self, ctx: CardContext, scheme: dict) -> str:
        photo_block = f"""
        <div class="product-stage">
          <img class="product-image" src="{ctx.photo_data_uri}" alt="{ctx.product_name}">
        </div>
        """ if ctx.has_photo else """
        <div class="product-stage text-hero">
          <div class="hero-diamond">&#9670;</div>
          <div class="hero-name">{product_name}</div>
        </div>
        """.format(product_name=ctx.product_name)

        return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
{self.base_styles()}
:root {{
{self.css_vars(scheme)}
}}
.ad {{
    width: 1080px; height: 1920px;
    background: radial-gradient(ellipse 70% 55% at 50% 42%, var(--bg-stage) 0%, var(--bg-outer) 60%, var(--bg-vignette) 100%);
    color: var(--ink); position: relative; overflow: hidden;
    display: flex; flex-direction: column; align-items: center;
    justify-content: space-between;
    padding: 70px 60px 50px;
}}
.ad::before {{
    content: ""; position: absolute; inset: 0; pointer-events: none; z-index: 1;
    background-image: radial-gradient(circle at 1px 1px, rgba(255,255,255,.02) 1px, transparent 0);
    background-size: 3px 3px; mix-blend-mode: overlay;
}}
.brand-header {{ text-align: center; position: relative; z-index: 2; }}
.brand-name {{
    font-family: 'Cormorant Garamond', serif; font-style: italic; font-weight: 500;
    font-size: 62px; letter-spacing: .01em; color: var(--accent); line-height: 1;
}}
.brand-category {{
    margin-top: 10px; font-size: 16px; font-weight: 500;
    letter-spacing: .42em; text-transform: uppercase; color: var(--ink-muted);
}}
.product-stage {{
    position: relative; z-index: 2;
    display: flex; align-items: center; justify-content: center;
    flex: 1; min-height: 0;
    width: 100%;
}}
.product-stage::before {{
    content: ""; position: absolute; width: 75%; height: 75%; border-radius: 50%;
    background: radial-gradient(circle, rgba(255,255,255,.06) 0%, transparent 55%);
    filter: blur(35px);
}}
.product-image {{
    position: relative; z-index: 2;
    max-width: 95%; max-height: 100%; object-fit: contain;
    border-radius: 8px;
    filter: drop-shadow(0 30px 50px rgba(0,0,0,.7)) drop-shadow(0 10px 20px rgba(0,0,0,.5));
}}
.text-hero {{ flex-direction: column; gap: 30px; }}
.hero-diamond {{ font-size: 80px; color: var(--accent); opacity: 0.3; }}
.hero-name {{
    font-family: 'Cormorant Garamond', serif; font-size: 76px; font-weight: 600;
    color: var(--ink); text-align: center; line-height: 1.15; max-width: 85%;
}}
.footer-block {{ text-align: center; position: relative; z-index: 2; width: 100%; }}
.product-code {{
    font-size: 20px; font-weight: 600; letter-spacing: .2em;
    color: var(--ink); margin-bottom: 12px;
}}
.product-price {{
    font-size: 76px; font-weight: 300; letter-spacing: .02em;
    color: var(--accent); margin-bottom: 24px; line-height: 1;
}}
.product-price span {{ font-size: 30px; vertical-align: super; margin-right: 2px; }}
.cta-btn {{
    display: inline-block; padding: 22px 64px;
    background: var(--accent); color: var(--bg-outer);
    font-size: 17px; font-weight: 600; letter-spacing: .28em; text-transform: uppercase;
    text-decoration: none; margin-bottom: 18px; border-radius: 4px;
}}
.website {{
    font-size: 14px; font-weight: 500; letter-spacing: .22em; text-transform: uppercase;
    color: var(--ink-muted);
    border-top: 1px solid rgba(255,255,255,.15); padding-top: 14px; margin-top: 4px;
}}
</style></head>
<body>
<div class="ad">
    <div class="brand-header">
        <div class="brand-name">{ctx.trader_name}</div>
        <div class="brand-category">{ctx.category or 'Curated Selection'}</div>
    </div>
    {photo_block}
    <div class="footer-block">
        <div class="product-code">{ctx.product_name}</div>
        <div class="product-price"><span>N</span>{ctx.price:,}</div>
        <a class="cta-btn" href="#">Message to Order &rarr;</a>
        <div class="website">{ctx.store_url}</div>
    </div>
</div>
</body></html>"""
