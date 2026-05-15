"""
Base class for animated video templates.

Video templates extend BaseTemplate but provide CSS @keyframes animations.
Elements are hidden initially and revealed sequentially when .animate is added.
"""


def animation_css() -> str:
    """Shared CSS animation utilities used by all video templates."""
    return """
/* All elements start hidden, animate when .animate is added */
.ad .anim { opacity: 0; transform: translateY(20px); }
.ad.animate .anim { animation: fadeSlideUp 0.6s ease forwards; }

/* Staggered delays */
.ad.animate .a1 { animation-delay: 0.1s; }
.ad.animate .a2 { animation-delay: 0.4s; }
.ad.animate .a3 { animation-delay: 0.9s; }
.ad.animate .a4 { animation-delay: 2.8s; }
.ad.animate .a5 { animation-delay: 3.4s; }
.ad.animate .a6 { animation-delay: 3.8s; }
.ad.animate .a7 { animation-delay: 4.2s; }

/* Photo has its own special animation */
.ad .photo-anim { opacity: 0; transform: scale(0.88); }
.ad.animate .photo-anim {
    animation: photoReveal 1.2s cubic-bezier(0.25, 0.46, 0.45, 0.94) 0.8s forwards;
}

/* Slow zoom on photo after reveal */
.ad.animate .photo-zoom {
    animation: slowZoom 5s ease-in-out 1.8s forwards;
}

/* Price glow pulse */
.ad.animate .price-glow {
    animation: fadeSlideUp 0.6s ease 3.2s forwards, glowPulse 1.5s ease 3.8s 2;
}

/* CTA button bounce */
.ad.animate .cta-anim {
    animation: fadeSlideUp 0.5s ease 3.8s forwards, ctaPulse 0.4s ease 4.3s 1;
}

@keyframes fadeSlideUp {
    from { opacity: 0; transform: translateY(20px); }
    to { opacity: 1; transform: translateY(0); }
}

@keyframes photoReveal {
    from { opacity: 0; transform: scale(0.88); }
    to { opacity: 1; transform: scale(1); }
}

@keyframes slowZoom {
    from { transform: scale(1); }
    to { transform: scale(1.06); }
}

@keyframes glowPulse {
    0%, 100% { filter: brightness(1); }
    50% { filter: brightness(1.3); }
}

@keyframes ctaPulse {
    0% { transform: translateY(0) scale(1); }
    50% { transform: translateY(-4px) scale(1.03); }
    100% { transform: translateY(0) scale(1); }
}

@keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
}
"""
