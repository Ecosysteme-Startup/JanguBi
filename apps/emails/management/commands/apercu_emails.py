"""Rend chaque e-mail du backend (HTML et texte) dans un dossier, pour relecture.

    python manage.py apercu_emails --dossier /tmp/apercus

Le logo est intégré à l'aperçu (image en data:) pour s'afficher hors ligne ; les e-mails
réels, eux, pointent vers EMAIL_LOGO_URL. ``--logo-url`` impose une autre adresse.
"""

import base64
from html import escape
from pathlib import Path
from typing import Any

from django.contrib.staticfiles import finders
from django.core.management.base import BaseCommand
from django.test import override_settings

from apps.emails.catalogue import CATALOGUE
from apps.emails.rendering import email_render


def _logo_data_uri() -> str:
    path = finders.find("emails/logo-email.png")
    if not path:
        return ""
    return "data:image/png;base64," + base64.b64encode(Path(str(path)).read_bytes()).decode()


class Command(BaseCommand):
    help = "Rend chaque e-mail (HTML et texte) dans un dossier, avec un index, pour relecture."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dossier", required=True, help="Dossier de sortie (créé au besoin).")
        parser.add_argument("--logo-url", default=None, help="Adresse du logo (défaut : logo intégré à l'aperçu).")

    def handle(self, *args: Any, **options: Any) -> None:
        dossier = Path(options["dossier"])
        dossier.mkdir(parents=True, exist_ok=True)
        logo = options["logo_url"] if options["logo_url"] is not None else _logo_data_uri()
        lignes = []
        with override_settings(EMAIL_LOGO_URL=logo):
            for spec in CATALOGUE:
                rendu = email_render(template=spec.template, context=spec.contexte())
                (dossier / f"{spec.nom}.html").write_text(rendu.html, encoding="utf-8")
                (dossier / f"{spec.nom}.txt").write_text(
                    f"Objet : {rendu.subject}\n\n{rendu.plain_text}", encoding="utf-8"
                )
                lignes.append(
                    f'<li><a href="{spec.nom}.html">{escape(spec.description)}</a>'
                    f"<span>Objet : {escape(rendu.subject)}</span>"
                    f'<a class="txt" href="{spec.nom}.txt">version texte</a></li>'
                )
        (dossier / "index.html").write_text(_INDEX.format(lignes="\n".join(lignes)), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"{len(CATALOGUE)} e-mails rendus dans {dossier}"))


_INDEX = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Aperçus des e-mails</title>
<style>
body {{ margin: 0; padding: 32px 16px; background: #F7FAFD; color: #0E1A2B; font: 16px/24px 'Libre Franklin', Arial, sans-serif; }}
main {{ max-width: 720px; margin: 0 auto; }}
h1 {{ font: 600 28px/36px 'Source Serif 4', Georgia, serif; margin: 0 0 8px; }}
p {{ color: #586677; margin: 0 0 24px; }}
ul {{ list-style: none; padding: 0; margin: 0; }}
li {{ background: #FFF; border: 1px solid #DDE5EE; border-radius: 12px; padding: 14px 18px; margin: 0 0 10px; }}
li a {{ color: #0A6BA3; font-weight: 600; text-decoration: none; }}
li span {{ display: block; color: #586677; font-size: 14px; }}
li a.txt {{ font-weight: 400; font-size: 14px; }}
</style></head>
<body><main>
<h1>Aperçus des e-mails de Jàngu Bi</h1>
<p>Rendus avec des données d'exemple par <code>manage.py apercu_emails</code>.</p>
<ul>
{lignes}
</ul>
</main></body></html>
"""
