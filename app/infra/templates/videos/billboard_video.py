"""
Video Template: Billboard — Animated split layout with sequential reveals.
"""

from app.infra.templates.base import BaseTemplate, CardContext
from app.infra.templates.video_base import animation_css
from app.infra.templates.cards.billboard import _GRADIENTS


class BillboardVideoTemplate(BaseTemplate):
    name = "billboard_video"
    display_name = "Billboard Video"

    def html(self, ctx: CardContext, scheme: dict) -> str:
        g = _GRADIENTS.get(scheme.get("name", "noir"), _GRADIENTS["noir"])

        photo_block = f"""
          <div class="photo-wrap photo-anim">
            <img class="product-image photo-zoom" src="{ctx.photo_data_uri}" alt="{ctx.product_name}">
          </div>
        """ if ctx.has_photo else """
          <div class="photo-wrap photo-anim">
            <div class="no-photo">{product_name}</div>
          </div>
        """.format(product_name=ctx.product_name)

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
{animation_css()}
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
.badge-dot{{width:20px;height:20px;border-radius:50%;background:{g['cta']};opacity:.8;display:inline-block;}}
.headline{{
    font-family:'Lobster',cursive;font-size:120px;line-height:.95;
    text-shadow:0 3px 0 {g['shadow']},0 6px 0 {g['shadow']},0 9px 0 {g['shadow']},0 14px 20px rgba(0,0,0,.4);
    transform:rotate(-3deg);transform-origin:left center;
    margin-bottom:36px;padding-right:5%;
}}
.headline .line2{{display:block;margin-left:8%}}
.body-copy{{
    font-family:'Playfair Display',serif;font-style:italic;
    font-size:22px;line-height:1.55;color:{g['body']};
    max-width:85%;margin-bottom:30px;text-shadow:0 1px 2px rgba(0,0,0,.2);
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
.price-text{{font-size:28px;font-weight:700;}}
.website{{font-size:15px;font-weight:500;letter-spacing:.02em;color:{g['body']};}}
.product-stage{{
    position:absolute;top:0;right:0;bottom:0;width:52%;z-index:2;
    display:flex;align-items:center;justify-content:center;padding:40px;
}}
.product-stage::before{{
    content:"";position:absolute;width:80%;height:80%;
    background:radial-gradient(circle,rgba(255,255,255,.08) 0%,transparent 60%);filter:blur(25px);
}}
.photo-wrap{{position:relative;z-index:2;display:flex;align-items:center;justify-content:center;overflow:hidden;border-radius:8px;}}
.product-image{{max-width:95%;max-height:95%;object-fit:contain;filter:drop-shadow(0 25px 40px rgba(0,0,0,.5)) drop-shadow(0 8px 16px rgba(0,0,0,.35));}}
.no-photo{{
    font-family:'Lobster',cursive;font-size:90px;text-align:center;line-height:1.1;
    text-shadow:0 3px 0 {g['shadow']},0 6px 0 {g['shadow']},0 10px 16px rgba(0,0,0,.4);
}}
</style></head>
<body>
<div class="ad">
    <div class="text-col">
        <div class="badge anim a1"><span class="badge-dot"></span>{ctx.category or 'Premium'}</div>
        <h1 class="headline anim a2">
            {line1}
            {"<span class='line2'>" + line2 + "</span>" if line2 else ""}
        </h1>
        <p class="body-copy anim a3">
            Available now from {ctx.trader_name}. Quality guaranteed.
            Message to order directly on WhatsApp.
        </p>
        <div class="cta-row">
            <div class="cta-anim" style="opacity:0;transform:translateY(20px);"><a class="cta" href="#">Message to Order <span class="arr">&rarr;</span></a></div>
            <span class="price-text anim price-glow" style="opacity:0;transform:translateY(20px);">{ctx.price_formatted}</span>
        </div>
        <div class="website anim a7">{ctx.store_url}</div>
    </div>
    <div class="product-stage">{photo_block}</div>
</div>
</body></html>"""
