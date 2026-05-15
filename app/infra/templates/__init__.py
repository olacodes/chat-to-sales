"""
Template registry — auto-discovers all templates in the cards/ folder.

Usage:
    from app.infra.templates import get_template, get_all_templates, pick_template

    tpl = pick_template(day_index=5, product_index=2)
    html = tpl.html(ctx, scheme)
"""

from app.infra.templates.base import BaseTemplate, CardContext
from app.infra.templates.schemes import SCHEMES, get_scheme

# Import all templates — each file registers itself
from app.infra.templates.cards.maison import MaisonTemplate
from app.infra.templates.cards.editorial import EditorialTemplate
from app.infra.templates.cards.showcase import ShowcaseTemplate
from app.infra.templates.cards.premium import PremiumTemplate

_REGISTRY: list[BaseTemplate] = [
    MaisonTemplate(),
    EditorialTemplate(),
    ShowcaseTemplate(),
    PremiumTemplate(),
]

_BY_NAME: dict[str, BaseTemplate] = {t.name: t for t in _REGISTRY}


def get_template(name: str) -> BaseTemplate | None:
    return _BY_NAME.get(name)


def get_all_templates() -> list[BaseTemplate]:
    return list(_REGISTRY)


def pick_template(day_index: int = 0, product_index: int = 0) -> BaseTemplate:
    """Deterministic template rotation."""
    idx = (day_index + product_index) % len(_REGISTRY)
    return _REGISTRY[idx]


def pick_random_template() -> BaseTemplate:
    """Random template for on-demand generation."""
    import random
    return random.choice(_REGISTRY)
