"""
Template: Billboard — Split layout, product right, bold text left.
Lobster headline with text shadow, gradient background, conic light rays.
"""

from app.infra.templates.base import BaseTemplate, CardContext

_GRADIENTS = {
    "noir":     {"warm": "#1a1a2e", "hot": "#0a0a14", "glow": "#2a2a4a", "edge": "#050510", "badge": "#ffffff", "badge_ink": "#0a0a14", "cta": "#ffffff", "cta_ink": "#0a0a14", "shadow": "#666688", "body": "#c8c8e0"},
    "gold":     {"warm": "#3a2a0a", "hot": "#1a1208", "glow": "#5a4a1a", "edge": "#0a0804", "badge": "#ffd97a", "badge_ink": "#1a1208", "cta": "#ffd97a", "cta_ink": "#1a1208", "shadow": "#c5a55a", "body": "#f0e8d0"},
    "emerald":  {"warm": "#0a3a1e", "hot": "#041a0e", "glow": "#1a5a30", "edge": "#020e06", "badge": "#25d366", "badge_ink": "#041a0e", "cta": "#25d366", "cta_ink": "#041a0e", "shadow": "#1a9a4a", "body": "#d0f0e0"},
    "midnight": {"warm": "#0d4a5c", "hot": "#062836", "glow": "#1a7390", "edge": "#041a24", "badge": "#ff4d6d", "badge_ink": "#ffffff", "cta": "#ff4d6d", "cta_ink": "#ffffff", "shadow": "#ff4d6d", "body": "#d4f1ff"},
    "rose":     {"warm": "#5c2020", "hot": "#2a0e0e", "glow": "#8a3030", "edge": "#180606", "badge": "#ff8a70", "badge_ink": "#2a0e0e", "cta": "#ff8a70", "cta_ink": "#2a0e0e", "shadow": "#d4916a", "body": "#ffe0d8"},
}


class BillboardTemplate(BaseTemplate):
    name = "billboard"
    display_name = "Billboard"

    def html(self, ctx: CardContext, scheme: dict) -> str:
        g = _GRADIENTS.get(scheme.get("name", "noir"), _GRADIENTS["noir"])

        photo_block = f"""
          <img class="product-image" src="{ctx.photo_data_uri}" alt="{ctx.product_name}">
        """ if ctx.has_photo else """
          <div class="no-photo">{product_name}</div>
        """.format(product_name=ctx.product_name)

        # Split product name into 2 lines for the headline
        words = ctx.product_name.split()
        if len(words) >= 2:
            mid = len(words) // 2
            line1 = " ".join(words[:mid])
            line2 = " ".join(words[mid:])
        else:
            line1 = ctx.product_name
            line2 = ""

        return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
@import url('https://fonts.googleapis.com/css2?family=Lobster&family=Playfair+Display:ital,wght@0,400;1,400;1,500&family=Inter:wght@300;400;500;600;700;800&display=swap');
*{{margin:0;padding:0;box-sizing:border-box}}
body{{margin:0;padding:0;font-family:'Inter',sans-serif;width:1080px;height:1920px;overflow:hidden;}}
.ad{{
    width:1080px;height:1920px;position:relative;overflow:hidden;color:#ffffff;
    background:
      radial-gradient(ellipse 70% 90% at 75% 55%,{g['glow']} 0%,{g['hot']} 45%,{g['edge']} 100%),
      linear-gradient(95deg,{g['warm']} 0%,{g['hot']} 100%);
}}
.ad::before{{
    content:"";position:absolute;top:50%;right:18%;width:120%;height:120%;
    background:conic-gradient(from 200deg at 0% 50%,transparent 0deg,rgba(255,255,255,.12) 4deg,transparent 8deg,transparent 14deg,rgba(255,255,255,.06) 18deg,transparent 22deg,transparent 32deg,rgba(255,255,255,.08) 36deg,transparent 42deg,transparent 60deg);
    transform:translate(-50%,-50%);pointer-events:none;mix-blend-mode:soft-light;opacity:.85;
}}
.ad::after{{
    content:"";position:absolute;inset:0;pointer-events:none;z-index:1;
    background-image:radial-gradient(circle at 1px 1px,rgba(0,0,0,.03) 1px,transparent 0);
    background-size:3px 3px;mix-blend-mode:multiply;
}}

.text-col{{
    position:absolute;top:0;bottom:0;left:0;width:55%;
    padding:80px 50px 60px 60px;z-index:3;
    display:flex;flex-direction:column;justify-content:center;
}}
.badge{{
    display:inline-flex;align-items:center;gap:8px;
    background:{g['badge']};color:{g['badge_ink']};
    padding:10px 20px 10px 14px;border-radius:999px;
    font-size:15px;font-weight:700;letter-spacing:.18em;text-transform:uppercase;
    align-self:flex-start;margin-bottom:24px;
    box-shadow:0 4px 14px rgba(0,0,0,.3);
}}
.badge-dot{{
    width:20px;height:20px;border-radius:50%;
    background:{g['cta']};opacity:.8;
    display:inline-block;
}}
.headline{{
    font-family:'Lobster',cursive;font-size:120px;line-height:.95;
    text-shadow:
      0 3px 0 {g['shadow']},
      0 6px 0 {g['shadow']},
      0 9px 0 {g['shadow']},
      0 14px 20px rgba(0,0,0,.4);
    transform:rotate(-3deg);transform-origin:left center;
    margin-bottom:36px;padding-right:5%;
}}
.headline .line2{{display:block;margin-left:8%}}
.body-copy{{
    font-family:'Playfair Display',serif;font-style:italic;
    font-size:22px;line-height:1.55;color:{g['body']};
    max-width:85%;margin-bottom:30px;
    text-shadow:0 1px 2px rgba(0,0,0,.2);
}}
.cta-row{{display:flex;align-items:center;gap:20px;flex-wrap:wrap;margin-bottom:20px;}}
.cta{{
    display:inline-flex;align-items:center;gap:10px;
    background:{g['cta']};color:{g['cta_ink']};
    padding:16px 32px;border-radius:999px;
    font-size:16px;font-weight:600;text-decoration:none;
    box-shadow:0 6px 18px rgba(0,0,0,.3);
}}
.cta .arr{{font-size:16px;font-weight:400}}
.price-text{{
    font-size:28px;font-weight:700;
}}
.website{{
    font-size:15px;font-weight:500;letter-spacing:.02em;
    color:{g['body']};
}}

.product-stage{{
    position:absolute;top:0;right:0;bottom:0;width:52%;z-index:2;
    display:flex;align-items:center;justify-content:center;padding:40px;
}}
.product-stage::before{{
    content:"";position:absolute;width:80%;height:80%;
    background:radial-gradient(circle,rgba(255,255,255,.08) 0%,transparent 60%);
    filter:blur(25px);
}}
.product-image{{
    position:relative;z-index:2;max-width:95%;max-height:95%;object-fit:contain;
    border-radius:8px;
    filter:drop-shadow(0 25px 40px rgba(0,0,0,.5)) drop-shadow(0 8px 16px rgba(0,0,0,.35));
}}
.no-photo{{
    font-family:'Lobster',cursive;font-size:90px;
    text-align:center;line-height:1.1;
    position:relative;z-index:2;
    text-shadow:0 3px 0 {g['shadow']},0 6px 0 {g['shadow']},0 10px 16px rgba(0,0,0,.4);
}}
</style></head>
<body>
<div class="ad">
    <div class="text-col">
        <div class="badge">
            <span class="badge-dot"></span>
            {ctx.category or 'Premium'}
        </div>
        <h1 class="headline">
            {line1}
            {"<span class='line2'>" + line2 + "</span>" if line2 else ""}
        </h1>
        <p class="body-copy">
            Available now from {ctx.trader_name}. Quality guaranteed.
            Message to order directly on WhatsApp.
        </p>
        <div class="cta-row">
            <a class="cta" href="#">Message to Order <span class="arr">&rarr;</span></a>
            <span class="price-text">{ctx.price_formatted}</span>
        </div>
        <div class="website">{ctx.store_url}</div>
    </div>
    <div class="product-stage">
        {photo_block}
    </div>
</div>
</body></html>"""
