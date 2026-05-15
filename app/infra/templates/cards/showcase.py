"""
Template: Showcase — Bold, modern. Brand+title top, photo center, price+CTA bottom.
"""

from app.infra.templates.base import BaseTemplate, CardContext


class ShowcaseTemplate(BaseTemplate):
    name = "showcase"
    display_name = "Showcase"

    def html(self, ctx: CardContext, scheme: dict) -> str:
        photo_block = f"""
          <img class="product-image" src="{ctx.photo_data_uri}" alt="{ctx.product_name}">
        """ if ctx.has_photo else """
          <div class="big-name">{product_name}</div>
        """.format(product_name=ctx.product_name)

        return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
{self.base_styles()}
:root {{ {self.css_vars(scheme)} }}
.ad {{
    width:1080px;height:1920px;position:relative;overflow:hidden;
    background:radial-gradient(ellipse 80% 60% at 50% 48%,var(--bg-stage) 0%,var(--bg-outer) 55%,var(--bg-vignette) 100%);
    color:var(--ink);
}}
.ad::before {{
    content:"";position:absolute;inset:0;pointer-events:none;
    background-image:radial-gradient(circle at 1px 1px,rgba(255,255,255,.018) 1px,transparent 0);
    background-size:3px 3px;
}}
.ad::after {{
    content:"";position:absolute;top:20%;left:-20%;width:140%;height:40%;
    background:radial-gradient(ellipse at center,rgba(255,255,255,.03) 0%,transparent 70%);
    transform:rotate(-8deg);pointer-events:none;
}}
.top {{
    position:absolute;top:50px;left:60px;right:60px;text-align:center;z-index:2;
}}
.brand-name {{
    font-size:20px;font-weight:600;letter-spacing:.4em;
    text-transform:uppercase;color:var(--accent);margin-bottom:10px;
}}
.hero-label {{
    font-size:15px;font-weight:500;letter-spacing:.35em;
    text-transform:uppercase;color:var(--accent);margin-bottom:8px;
}}
.hero-name {{
    font-family:'Cormorant Garamond',serif;font-size:60px;font-weight:600;
    color:var(--ink);line-height:1.1;
}}
.photo-zone {{
    position:absolute;top:260px;left:40px;right:40px;bottom:340px;
    display:flex;align-items:center;justify-content:center;z-index:2;
}}
.photo-zone::before {{
    content:"";position:absolute;width:65%;height:60%;border-radius:50%;
    background:radial-gradient(circle,rgba(255,255,255,.05) 0%,transparent 55%);
    filter:blur(30px);
}}
.product-image {{
    position:relative;z-index:2;width:100%;height:auto;
    border-radius:8px;
    filter:drop-shadow(0 30px 55px rgba(0,0,0,.7)) drop-shadow(0 10px 20px rgba(0,0,0,.5));
}}
.big-name {{
    font-family:'Cormorant Garamond',serif;font-size:84px;font-weight:600;
    color:var(--ink);text-align:center;line-height:1.1;
}}
.bottom {{
    position:absolute;bottom:40px;left:60px;right:60px;text-align:center;z-index:2;
}}
.price {{
    font-size:76px;font-weight:300;color:var(--accent);line-height:1;margin-bottom:18px;
}}
.price span {{ font-size:28px;vertical-align:super;margin-right:2px; }}
.cta-btn {{
    display:inline-block;padding:20px 64px;
    background:var(--accent);color:var(--bg-outer);
    font-size:17px;font-weight:600;letter-spacing:.3em;text-transform:uppercase;
    text-decoration:none;margin-bottom:14px;border-radius:4px;
}}
.footer {{
    display:flex;justify-content:space-between;width:100%;
    font-size:14px;font-weight:500;letter-spacing:.18em;
    text-transform:uppercase;color:var(--ink-muted);
    padding-top:10px;border-top:1px solid rgba(255,255,255,.12);
}}
</style></head>
<body>
<div class="ad">
    <div class="top">
        <div class="brand-name">{ctx.trader_name}</div>
        <div class="hero-label">{ctx.category or 'New Collection'}</div>
        <div class="hero-name">{ctx.product_name}</div>
    </div>
    <div class="photo-zone">{photo_block}</div>
    <div class="bottom">
        <div class="price"><span>N</span>{ctx.price:,}</div>
        <a class="cta-btn" href="#">Order Now &rarr;</a>
        <div class="footer">
            <span>chattosales.com</span>
            <span>/stores/{ctx.slug}</span>
        </div>
    </div>
</div>
</body></html>"""
