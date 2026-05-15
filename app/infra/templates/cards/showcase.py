"""
Template: Showcase — Bold, modern. Brand top, large product, prominent price + CTA.
"""

from app.infra.templates.base import BaseTemplate, CardContext


class ShowcaseTemplate(BaseTemplate):
    name = "showcase"
    display_name = "Showcase"

    def html(self, ctx: CardContext, scheme: dict) -> str:
        photo_block = f"""
        <div class="product-stage">
          <img class="product-image" src="{ctx.photo_data_uri}" alt="{ctx.product_name}">
        </div>
        """ if ctx.has_photo else """
        <div class="product-stage text-only">
          <div class="big-name">{product_name}</div>
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
    background: radial-gradient(ellipse 80% 60% at 50% 48%, var(--bg-stage) 0%, var(--bg-outer) 55%, var(--bg-vignette) 100%);
    color: var(--ink); position: relative; overflow: hidden;
    display: flex; flex-direction: column; align-items: center;
    padding: 50px 60px 40px;
}}
.ad::before {{
    content: ""; position: absolute; inset: 0; pointer-events: none;
    background-image: radial-gradient(circle at 1px 1px, rgba(255,255,255,.018) 1px, transparent 0);
    background-size: 3px 3px;
}}
/* Decorative glow wave */
.ad::after {{
    content: ""; position: absolute; top: 20%; left: -20%; width: 140%; height: 40%;
    background: radial-gradient(ellipse at center, rgba(255,255,255,.03) 0%, transparent 70%);
    transform: rotate(-8deg); pointer-events: none;
}}
.brand {{
    text-align: center; position: relative; z-index: 2; margin-bottom: 10px;
}}
.brand-name {{
    font-size: 18px; font-weight: 600; letter-spacing: .4em;
    text-transform: uppercase; color: var(--accent);
}}
.hero-title {{
    text-align: center; position: relative; z-index: 2; margin-bottom: 4px;
}}
.hero-label {{
    font-size: 14px; font-weight: 500; letter-spacing: .35em;
    text-transform: uppercase; color: var(--accent); margin-bottom: 6px;
}}
.hero-name {{
    font-family: 'Cormorant Garamond', serif; font-size: 56px; font-weight: 600;
    color: var(--ink); line-height: 1.1;
}}
.product-stage {{
    flex: 1; display: flex; align-items: center; justify-content: center;
    position: relative; z-index: 2; width: 100%;
}}
.product-stage::before {{
    content: ""; position: absolute; width: 65%; height: 60%; border-radius: 50%;
    background: radial-gradient(circle, rgba(255,255,255,.05) 0%, transparent 55%);
    filter: blur(30px);
}}
.product-image {{
    position: relative; z-index: 2;
    max-width: 92%; max-height: 100%; object-fit: contain;
    mix-blend-mode: lighten;
    filter: drop-shadow(0 30px 55px rgba(0,0,0,.6)) drop-shadow(0 8px 18px rgba(0,0,0,.4));
}}
.text-only {{ align-items: center; justify-content: center; }}
.big-name {{
    font-family: 'Cormorant Garamond', serif; font-size: 80px; font-weight: 600;
    color: var(--ink); text-align: center; line-height: 1.1; max-width: 90%;
}}
.bottom {{
    text-align: center; position: relative; z-index: 2; width: 100%;
}}
.price {{
    font-size: 72px; font-weight: 300; color: var(--accent); line-height: 1;
    margin-bottom: 24px;
}}
.price span {{ font-size: 26px; vertical-align: super; margin-right: 2px; }}
.cta-btn {{
    display: inline-block; padding: 22px 68px;
    background: var(--accent); color: var(--bg-outer);
    font-size: 16px; font-weight: 600; letter-spacing: .3em; text-transform: uppercase;
    text-decoration: none; margin-bottom: 20px; border-radius: 4px;
}}
.footer {{
    display: flex; justify-content: space-between; width: 100%;
    font-size: 12px; font-weight: 500; letter-spacing: .2em;
    text-transform: uppercase; color: var(--ink-fine);
    padding-top: 12px; border-top: 1px solid rgba(255,255,255,.08);
}}
</style></head>
<body>
<div class="ad">
    <div class="brand">
        <div class="brand-name">{ctx.trader_name}</div>
    </div>
    <div class="hero-title">
        <div class="hero-label">{ctx.category or 'New Collection'}</div>
        <div class="hero-name">{ctx.product_name}</div>
    </div>
    {photo_block}
    <div class="bottom">
        <div class="price"><span>N</span>{ctx.price:,}</div>
        <a class="cta-btn" href="#">Order Now &nbsp;&rarr;</a>
        <div class="footer">
            <span>chattosales.com</span>
            <span>/stores/{ctx.slug}</span>
        </div>
    </div>
</div>
</body></html>"""
