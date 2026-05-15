"""
Template: Editorial — Brand header with badge, product hero, elegant price section.
"""

from app.infra.templates.base import BaseTemplate, CardContext


class EditorialTemplate(BaseTemplate):
    name = "editorial"
    display_name = "Editorial"

    def html(self, ctx: CardContext, scheme: dict) -> str:
        photo_block = f"""
          <img class="product-image" src="{ctx.photo_data_uri}" alt="{ctx.product_name}">
        """ if ctx.has_photo else """
          <div class="text-ornament">&#9670;</div>
          <div class="text-product">{product_name}</div>
        """.format(product_name=ctx.product_name)

        return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
{self.base_styles()}
:root {{ {self.css_vars(scheme)} }}
.ad {{
    width:1080px;height:1920px;position:relative;overflow:hidden;
    background:linear-gradient(170deg,var(--bg-stage) 0%,var(--bg-outer) 40%,var(--bg-vignette) 100%);
    color:var(--ink);
}}
.ad::before {{
    content:"";position:absolute;inset:0;pointer-events:none;
    background-image:radial-gradient(circle at 1px 1px,rgba(255,255,255,.015) 1px,transparent 0);
    background-size:4px 4px;
}}
.header {{
    position:absolute;top:40px;left:60px;right:60px;
    display:flex;justify-content:space-between;align-items:flex-start;z-index:2;
}}
.brand-name {{
    font-family:'Cormorant Garamond',serif;font-style:italic;font-weight:500;
    font-size:56px;color:var(--accent);line-height:1;
}}
.brand-sub {{
    font-size:14px;font-weight:500;letter-spacing:.35em;
    text-transform:uppercase;color:var(--ink-muted);margin-top:6px;
}}
.badge {{
    border:1px solid var(--accent);padding:8px 18px;
    font-size:13px;font-weight:600;letter-spacing:.3em;
    text-transform:uppercase;color:var(--accent);margin-top:8px;border-radius:4px;
}}
.photo-zone {{
    position:absolute;top:170px;left:40px;right:40px;bottom:420px;
    display:flex;align-items:center;justify-content:center;z-index:2;
}}
.photo-zone::before {{
    content:"";position:absolute;width:70%;height:70%;border-radius:50%;
    background:radial-gradient(circle,rgba(255,255,255,.05) 0%,transparent 55%);
    filter:blur(25px);
}}
.product-image {{
    position:relative;z-index:2;width:100%;height:auto;
    border-radius:8px;
    filter:drop-shadow(0 30px 50px rgba(0,0,0,.7)) drop-shadow(0 10px 20px rgba(0,0,0,.5));
}}
.text-ornament {{ font-size:60px;color:var(--accent);opacity:0.25;text-align:center; }}
.text-product {{
    font-family:'Cormorant Garamond',serif;font-size:72px;font-weight:600;
    color:var(--ink);text-align:center;line-height:1.15;
}}
.bottom {{
    position:absolute;bottom:40px;left:60px;right:60px;z-index:2;
}}
.product-title {{
    font-size:20px;font-weight:600;letter-spacing:.2em;
    color:var(--ink);text-align:center;margin-bottom:14px;
}}
.price-row {{
    display:flex;justify-content:space-between;align-items:baseline;
    padding:12px 0;
    border-top:1px solid rgba(255,255,255,.12);
    border-bottom:1px solid rgba(255,255,255,.12);
    margin-bottom:18px;
}}
.price-label {{
    font-size:15px;font-weight:400;letter-spacing:.2em;
    text-transform:uppercase;color:var(--ink-muted);
}}
.price-value {{
    font-size:64px;font-weight:300;color:var(--accent);line-height:1;
}}
.price-value span {{ font-size:24px;vertical-align:super; }}
.cta-btn {{
    display:block;text-align:center;padding:20px;
    background:var(--accent);color:var(--bg-outer);
    font-size:17px;font-weight:600;letter-spacing:.3em;text-transform:uppercase;
    text-decoration:none;margin-bottom:14px;border-radius:4px;
}}
.footer-row {{
    display:flex;justify-content:space-between;
    font-size:14px;font-weight:500;letter-spacing:.18em;
    text-transform:uppercase;color:var(--ink-muted);
    border-top:1px solid rgba(255,255,255,.1);padding-top:10px;
}}
</style></head>
<body>
<div class="ad">
    <div class="header">
        <div>
            <div class="brand-name">{ctx.trader_name}</div>
            <div class="brand-sub">{ctx.category or 'Curated Selection'}</div>
        </div>
        <div class="badge">&#9733; Authentic</div>
    </div>
    <div class="photo-zone">{photo_block}</div>
    <div class="bottom">
        <div class="product-title">{ctx.product_name}</div>
        <div class="price-row">
            <div class="price-label">Price</div>
            <div class="price-value"><span>N</span>{ctx.price:,}</div>
        </div>
        <a class="cta-btn" href="#">Message to Order &rarr;</a>
        <div class="footer-row">
            <span>chattosales.com</span>
            <span>/stores/{ctx.slug}</span>
        </div>
    </div>
</div>
</body></html>"""
