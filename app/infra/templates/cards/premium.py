"""
Template: Premium — Vibrant gradient, script font header, rotated price badge,
decorative dots + wave SVG. Bold, eye-catching social media ad style.
"""

from app.infra.templates.base import BaseTemplate, CardContext

# Gradient color sets — mapped to our scheme system
_GRADIENTS = {
    "noir":     {"light": "#1a2440", "dark": "#0a0e1a", "accent_bg": "#142030"},
    "gold":     {"light": "#2a1f0a", "dark": "#120e04", "accent_bg": "#1e1608"},
    "emerald":  {"light": "#0a2a1a", "dark": "#04120a", "accent_bg": "#081e10"},
    "midnight": {"light": "#1a1040", "dark": "#0a0618", "accent_bg": "#140e30"},
    "rose":     {"light": "#3a1418", "dark": "#180808", "accent_bg": "#2a0e10"},
}


class PremiumTemplate(BaseTemplate):
    name = "premium"
    display_name = "Premium"

    def html(self, ctx: CardContext, scheme: dict) -> str:
        grad = _GRADIENTS.get(scheme.get("name", "noir"), _GRADIENTS["noir"])

        photo_block = f"""
          <img class="product-image" src="{ctx.photo_data_uri}" alt="{ctx.product_name}">
        """ if ctx.has_photo else """
          <div class="no-photo-name">{product_name}</div>
        """.format(product_name=ctx.product_name)

        # Format price short (e.g. N250k for >=1000, N500 for <1000)
        if ctx.price >= 1_000_000:
            price_short = f"N{ctx.price / 1_000_000:.1f}m"
        elif ctx.price >= 1_000:
            price_short = f"N{ctx.price // 1_000}k"
        else:
            price_short = f"N{ctx.price:,}"

        return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
@import url('https://fonts.googleapis.com/css2?family=Allura&family=Playfair+Display:ital,wght@0,700;1,400&family=Inter:wght@300;400;500;600;700&display=swap');
{self.photo_adaptive_css()}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{
    margin:0;padding:0;
    font-family:'Inter',sans-serif;
    width:1080px;height:1920px;overflow:hidden;
}}
.ad{{
    width:1080px;height:1920px;position:relative;overflow:hidden;
    background:
      radial-gradient(ellipse at 30% 35%,{grad['accent_bg']} 0%,transparent 55%),
      linear-gradient(165deg,{grad['light']} 0%,{grad['dark']} 100%);
    color:{scheme['ink']};
}}

/* ── Decorative elements ── */
.dots-tr{{
    position:absolute;top:50px;right:50px;
    width:100px;height:70px;
    background-image:radial-gradient(circle,rgba(255,255,255,.12) 1.5px,transparent 1.5px);
    background-size:14px 14px;z-index:1;
}}
.dots-bl{{
    position:absolute;bottom:420px;left:40px;
    width:70px;height:90px;
    background-image:radial-gradient(circle,rgba(255,255,255,.12) 1.5px,transparent 1.5px);
    background-size:14px 14px;z-index:1;
}}
.wave-left{{
    position:absolute;left:30px;top:35%;z-index:1;
    color:rgba(255,255,255,.12);
}}
.float-1{{
    position:absolute;top:28%;right:12%;
    width:16px;height:16px;border-radius:50%;
    background:rgba(255,255,255,.1);z-index:1;
}}
.float-2{{
    position:absolute;bottom:38%;left:16%;
    width:10px;height:10px;border-radius:50%;
    background:{scheme['accent']};opacity:.4;z-index:1;
}}

/* ── Header ── */
.header{{
    position:absolute;top:60px;left:0;right:0;
    text-align:center;z-index:3;
    padding:0 60px;
}}
.script{{
    font-family:'Allura',cursive;
    font-size:72px;color:{scheme['accent']};
    line-height:.7;margin-bottom:10px;
}}
.header h1{{
    font-family:'Playfair Display',serif;font-weight:700;
    font-size:62px;letter-spacing:.02em;line-height:1;
    text-transform:uppercase;
}}
.header h1 .light{{
    font-style:italic;font-weight:400;
    text-transform:capitalize;letter-spacing:0;
}}

/* ── Price badge ── */
.price-badge{{
    position:absolute;top:320px;right:50px;
    z-index:4;text-align:center;
    transform:rotate(-8deg);
}}
.price-badge .amount{{
    font-family:'Playfair Display',serif;font-weight:700;font-style:italic;
    font-size:72px;color:{scheme['accent']};line-height:.9;
    text-shadow:0 2px 10px rgba(0,0,0,.3);
}}
.price-badge .small{{
    font-size:12px;font-weight:500;letter-spacing:.18em;
    text-transform:uppercase;color:{scheme['ink_muted']};margin-top:6px;
}}

/* ── Product stage ── */
.product-stage{{
    position:absolute;top:440px;bottom:340px;left:40px;right:40px;
    display:flex;align-items:center;justify-content:center;z-index:2;
}}
.product-stage::before{{
    content:"";position:absolute;width:85%;height:85%;
    background:radial-gradient(ellipse at center,rgba(255,255,255,.1) 0%,transparent 60%);
    filter:blur(25px);
}}
.product-image{{
    position:relative;z-index:2;
}}
.no-photo-name{{
    font-family:'Playfair Display',serif;font-size:80px;font-weight:700;
    color:{scheme['ink']};text-align:center;line-height:1.1;
    position:relative;z-index:2;
}}

/* ── Footer ── */
.footer{{
    position:absolute;bottom:40px;left:50px;right:50px;z-index:5;
    display:flex;justify-content:space-between;align-items:center;
}}
.logo{{
    font-family:'Playfair Display',serif;font-weight:700;font-style:italic;
    font-size:28px;letter-spacing:.04em;
}}
.logo small{{
    display:block;font-family:'Inter',sans-serif;font-style:normal;
    font-weight:400;font-size:10px;letter-spacing:.3em;
    text-transform:uppercase;color:{scheme['ink_muted']};margin-top:-2px;
}}
.cta{{
    display:inline-flex;align-items:center;gap:10px;
    background:{scheme['accent']};color:{grad['dark']};
    padding:16px 36px;border-radius:999px;
    font-size:13px;font-weight:600;letter-spacing:.18em;
    text-transform:uppercase;text-decoration:none;
    box-shadow:0 8px 24px rgba(0,0,0,.3);
}}
.cta .arr{{font-size:16px;letter-spacing:0}}
.store-url{{
    font-size:12px;font-weight:500;letter-spacing:.15em;
    text-transform:uppercase;color:{scheme['ink_muted']};
    text-align:right;
}}
</style></head>
<body>
<div class="ad {"photo-light" if ctx.photo_is_light else "photo-dark"}">
    <!-- Decorative -->
    <div class="dots-tr"></div>
    <div class="dots-bl"></div>
    <div class="float-1"></div>
    <div class="float-2"></div>
    <svg class="wave-left" width="50" height="160" viewBox="0 0 40 120" fill="none">
      <path d="M 5 0 Q 25 15 5 30 Q 25 45 5 60 Q 25 75 5 90 Q 25 105 5 120" stroke="currentColor" stroke-width="2" fill="none"/>
    </svg>

    <!-- Header -->
    <div class="header">
        <div class="script">Premium</div>
        <h1>{ctx.product_name.split()[0] if ctx.product_name else 'Product'} <span class="light">Collection</span></h1>
    </div>

    <!-- Price badge -->
    <div class="price-badge">
        <div class="amount">{price_short}</div>
        <div class="small">Available<br>now</div>
    </div>

    <!-- Product -->
    <div class="product-stage">
        {photo_block}
    </div>

    <!-- Footer -->
    <div class="footer">
        <div class="logo">{ctx.trader_name}<small>{ctx.category or 'store'}</small></div>
        <a class="cta" href="#">Message to Order <span class="arr">&rarr;</span></a>
        <div class="store-url">{ctx.store_url}</div>
    </div>
</div>
</body></html>"""
