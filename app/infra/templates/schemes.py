"""
Color scheme definitions for Status Kit templates.

Each scheme provides CSS variable values injected into templates.
"""

SCHEMES = [
    {
        "name": "noir",
        "bg_outer": "#0a0a0a",
        "bg_stage": "#1a1a1a",
        "bg_vignette": "#050505",
        "ink": "#ffffff",
        "ink_muted": "#c8c8c8",
        "ink_fine": "#888888",
        "accent": "#ffffff",
    },
    {
        "name": "gold",
        "bg_outer": "#0a0908",
        "bg_stage": "#1a1710",
        "bg_vignette": "#050403",
        "ink": "#f0ede6",
        "ink_muted": "#c8c0a8",
        "ink_fine": "#8a8570",
        "accent": "#c5a55a",
    },
    {
        "name": "emerald",
        "bg_outer": "#060e0a",
        "bg_stage": "#0e1e14",
        "bg_vignette": "#030805",
        "ink": "#e6f0ea",
        "ink_muted": "#a8c8b0",
        "ink_fine": "#608870",
        "accent": "#25d366",
    },
    {
        "name": "midnight",
        "bg_outer": "#080a10",
        "bg_stage": "#10141e",
        "bg_vignette": "#030408",
        "ink": "#e6eaf0",
        "ink_muted": "#a8b0c8",
        "ink_fine": "#606888",
        "accent": "#80a0dc",
    },
    {
        "name": "rose",
        "bg_outer": "#0e0808",
        "bg_stage": "#1e1210",
        "bg_vignette": "#080303",
        "ink": "#f0e8e6",
        "ink_muted": "#c8b0a8",
        "ink_fine": "#886860",
        "accent": "#d4916a",
    },
]


def get_scheme(index: int) -> dict:
    return SCHEMES[index % len(SCHEMES)]
