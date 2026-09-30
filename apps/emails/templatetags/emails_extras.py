"""Outils des gabarits d'e-mails."""

from typing import Any

from django import template

register = template.Library()


@register.simple_tag
def concat(*parts: Any) -> str:
    """``{% concat frontend_url "/agenda/" event_id as url %}`` : adresse construite par morceaux."""
    return "".join(str(part) for part in parts if part is not None)


@register.filter
def fcfa(amount: Any) -> str:
    """Montant en francs CFA, milliers séparés par une espace insécable fine : « 25 000 FCFA »."""
    try:
        value = int(amount)
    except (TypeError, ValueError):
        return ""
    return f"{value:,}".replace(",", " ") + " FCFA"
