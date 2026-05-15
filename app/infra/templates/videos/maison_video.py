"""
Video Template: Maison — Animated sequential reveal.

0.1s  Brand name fades up
0.4s  Category fades up
0.8s  Product photo scales in from 88% → 100%
1.8s  Photo slowly zooms (subtle)
2.8s  Product name slides up
3.2s  Price appears with glow
3.8s  CTA slides up with bounce
4.2s  Footer fades in
"""

from app.infra.templates.base import BaseTemplate, CardContext
from app.infra.templates.video_base import animation_css


class MaisonVideoTemplate(BaseTemplate):
    name = "maison_video"
    display_name = "Maison Video"

    def html(self, ctx: CardContext, scheme: dict) -> str:
        photo_block = f"""
          <div class="photo-wrap photo-anim">
            <img class="product-image photo-zoom" src="{ctx.photo_data_uri}" alt="{ctx.product_name}">
          </div>
        """ if ctx.has_photo else """
          <div class="hero-text photo-anim">
            <div class="hero-diamond">&#9670;</div>
            <div class="hero-name">{product_name}</div>
          </div>
        """.format(product_name=ctx.product_name)

        return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
{self.base_styles()}
:root {{ {self.css_vars(scheme)} }}
{animation_css()}
.ad {{
    width:1080px;height:1920px;position:relative;overflow:hidden;
    background:radial-gradient(ellipse 70% 55% at 50% 42%,var(--bg-stage) 0%,var(--bg-outer) 60%,var(--bg-vignette) 100%);
    color:var(--ink);
}}
.ad::before {{
    content:"";position:absolute;inset:0;pointer-events:none;z-index:1;
    background-image:radial-gradient(circle at 1px 1px,rgba(255,255,255,.02) 1px,transparent 0);
    background-size:3px 3px;mix-blend-mode:overlay;
}}
.brand {{
    position:absolute;top:50px;left:0;right:0;text-align:center;z-index:2;
}}
.brand-name {{
    font-family:'Cormorant Garamond',serif;font-style:italic;font-weight:500;
    font-size:62px;color:var(--accent);line-height:1;
}}
.brand-sub {{
    margin-top:10px;font-size:16px;font-weight:500;
    letter-spacing:.42em;text-transform:uppercase;color:var(--ink-muted);
}}
.photo-zone {{
    position:absolute;top:200px;left:40px;right:40px;bottom:380px;
    display:flex;align-items:center;justify-content:center;z-index:2;
}}
.photo-zone::before {{
    content:"";position:absolute;width:70%;height:70%;border-radius:50%;
    background:radial-gradient(circle,rgba(255,255,255,.06) 0%,transparent 55%);
    filter:blur(35px);
}}
.photo-wrap {{
    position:relative;z-index:2;width:100%;
    display:flex;align-items:center;justify-content:center;
    overflow:hidden;border-radius:8px;
}}
.product-image {{
    width:100%;height:auto;display:block;
    filter:drop-shadow(0 30px 50px rgba(0,0,0,.7));
}}
.hero-text {{ text-align:center; }}
.hero-diamond {{ font-size:80px;color:var(--accent);opacity:0.3; }}
.hero-name {{
    font-family:'Cormorant Garamond',serif;font-size:76px;font-weight:600;
    color:var(--ink);line-height:1.15;
}}
.bottom {{
    position:absolute;bottom:40px;left:60px;right:60px;text-align:center;z-index:2;
}}
.product-code {{
    font-size:20px;font-weight:600;letter-spacing:.2em;color:var(--ink);margin-bottom:10px;
}}
.product-price {{
    font-size:76px;font-weight:300;color:var(--accent);margin-bottom:20px;line-height:1;
}}
.product-price span {{ font-size:30px;vertical-align:super;margin-right:2px; }}
.cta-btn {{
    display:inline-block;padding:20px 60px;
    background:var(--accent);color:var(--bg-outer);
    font-size:17px;font-weight:600;letter-spacing:.28em;text-transform:uppercase;
    text-decoration:none;margin-bottom:14px;border-radius:4px;
}}
.website {{
    font-size:14px;font-weight:500;letter-spacing:.22em;text-transform:uppercase;
    color:var(--ink-muted);border-top:1px solid rgba(255,255,255,.15);padding-top:12px;
}}
</style></head>
<body>
<div class="ad">
    <div class="brand">
        <div class="brand-name anim a1">{ctx.trader_name}</div>
        <div class="brand-sub anim a2">{ctx.category or 'Curated Selection'}</div>
    </div>
    <div class="photo-zone">
        {photo_block}
    </div>
    <div class="bottom">
        <div class="product-code anim a4">{ctx.product_name}</div>
        <div class="product-price anim price-glow" style="opacity:0;transform:translateY(20px);">{ctx.price_formatted}</div>
        <div class="cta-anim" style="opacity:0;transform:translateY(20px);">
            <a class="cta-btn" href="#">Message to Order &rarr;</a>
        </div>
        <div class="website anim a7">{ctx.store_url}</div>
    </div>
</div>
</body></html>"""
