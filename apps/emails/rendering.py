"""Rendu des e-mails de Jàngu Bi : un gabarit de base unique (``emails/base.html`` et
``emails/base.txt``), CSS mis en ligne, version texte systématique.

Chaque e-mail tient en trois gabarits voisins : ``<nom>_subject.txt``, ``<nom>.html`` (qui
étend ``emails/base.html``) et ``<nom>.txt`` (qui étend ``emails/base.txt``).
"""

import re
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone, translation

from apps.emails.inline import css_inline


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    html: str
    plain_text: str


def brand_context() -> dict[str, Any]:
    """Variables communes à tous les e-mails (logo, liens du pied de page)."""
    return {
        "logo_url": getattr(settings, "EMAIL_LOGO_URL", ""),
        "frontend_url": str(getattr(settings, "FRONTEND_URL", "") or "").rstrip("/"),
        "diocese_nom": getattr(settings, "EMAIL_DIOCESE_NAME", "Archidiocèse de Dakar"),
        "annee": timezone.localdate().year,
    }


def _clean_text(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


def email_render(*, template: str, context: dict[str, Any] | None = None) -> RenderedEmail:
    """Rend l'objet, le HTML (CSS en ligne) et le texte de ``template`` (ex. ``invitations/invitation_clerge``)."""
    ctx = {**brand_context(), **(context or {})}
    # Dates et jours en français, quelle que soit la langue du processus (tâches Celery).
    with translation.override("fr"):
        subject = " ".join(render_to_string(f"{template}_subject.txt", ctx).split())
        html = css_inline(render_to_string(f"{template}.html", ctx))
        plain_text = _clean_text(render_to_string(f"{template}.txt", ctx))
    return RenderedEmail(subject=subject[:255], html=html, plain_text=plain_text)
