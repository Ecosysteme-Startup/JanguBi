"""Rendu des e-mails : gabarit de base unique, CSS en ligne, version texte, catalogue complet."""

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command
from django.template import Context, Template
from django.test import override_settings

from apps.emails.catalogue import CATALOGUE
from apps.emails.inline import css_inline
from apps.emails.rendering import email_render
from apps.emails.services import _from_address

TEMPLATES_DIR = Path(settings.BASE_DIR) / "apps" / "templates"
LOGO = "https://api.example.sn/static/emails/logo-email.png"


def _all_email_templates() -> set[str]:
    return {
        str(path.relative_to(TEMPLATES_DIR)).removesuffix("_subject.txt")
        for path in TEMPLATES_DIR.rglob("*_subject.txt")
    }


def test_catalogue_couvre_tous_les_gabarits():
    """Tout e-mail du backend figure au catalogue (aperçus et tests de rendu)."""
    assert _all_email_templates() == {spec.template for spec in CATALOGUE}


@override_settings(EMAIL_LOGO_URL=LOGO, FRONTEND_URL="https://jangubi.example.sn/")
@pytest.mark.parametrize("spec", CATALOGUE, ids=lambda spec: spec.nom)
def test_chaque_email_suit_le_gabarit_de_base(spec):
    rendu = email_render(template=spec.template, context=spec.contexte())

    # Objet : une ligne, sans préfixe technique.
    assert rendu.subject and "\n" not in rendu.subject
    assert not rendu.subject.startswith("[")

    # HTML : logo PNG hébergé, pied de page, CSS en ligne, aucune feuille à mettre en ligne restante.
    html = rendu.html
    assert f'src="{LOGO}"' in html
    assert "Archidiocèse de Dakar" in html
    assert "loi n° 2008-12" in html
    assert "https://jangubi.example.sn/confidentialite" in html
    assert "data-inline" not in html
    assert 'class="card-body" style="' in html
    assert re.search(r'<h1 style="[^"]*font-family', html)
    assert "{{" not in html and "{%" not in html

    # Texte : systématique, sans balises, avec le même pied de page.
    text = rendu.plain_text
    assert text.strip()
    assert not re.search(r"</?[a-z][a-z0-9]*[\s>/]", text)
    assert "&#x27;" not in text and "&amp;" not in text
    assert "Archidiocèse de Dakar" in text

    # Ni « IA », ni devise autre que le franc CFA.
    for contenu in (rendu.subject, html, text):
        assert not re.search(r"\bIA\b", contenu)
        assert not re.search(r"€|\bEUR\b|\bUSD\b|\$\s?\d", contenu)


def test_montant_du_recu_en_fcfa():
    spec = next(s for s in CATALOGUE if s.nom == "don_recu")
    rendu = email_render(template=spec.template, context=spec.contexte())
    assert "25 000 FCFA" in rendu.html
    assert "25 000 FCFA" in rendu.plain_text
    assert "reçu fiscal" in rendu.plain_text


def test_dates_en_francais_meme_si_la_langue_du_processus_est_l_anglais():
    spec = next(s for s in CATALOGUE if s.nom == "evenement_rappel")
    rendu = email_render(template=spec.template, context=spec.contexte())
    mois = (
        "janvier",
        "février",
        "mars",
        "avril",
        "mai",
        "juin",
        "juillet",
        "août",
        "septembre",
        "octobre",
        "novembre",
        "décembre",
    )
    assert any(m in rendu.plain_text for m in mois)
    assert not re.search(
        r"\b(January|February|March|April|June|July|August|September|October|November|December)\b", rendu.plain_text
    )


def test_contenu_saisi_echappe_dans_le_html():
    """Le message d'une paroisse est une saisie libre : jamais injecté tel quel dans le HTML."""
    spec = next(s for s in CATALOGUE if s.nom == "acte_complement")
    ctx = {**spec.contexte(), "complement": '<script>alert("x")</script> Merci'}
    rendu = email_render(template=spec.template, context=ctx)
    assert "<script>" not in rendu.html
    assert "&lt;script&gt;" in rendu.html
    assert '<script>alert("x")</script> Merci' in rendu.plain_text


def test_rendez_vous_ne_nomme_pas_la_confession():
    """Donnée religieuse sensible : l'objet et le corps restent discrets (« rendez-vous »)."""
    for nom in ("rendez_vous_rappel", "rendez_vous_annule"):
        spec = next(s for s in CATALOGUE if s.nom == nom)
        rendu = email_render(template=spec.template, context=spec.contexte())
        for contenu in (rendu.subject, rendu.html, rendu.plain_text):
            assert "confess" not in contenu.lower()


@override_settings(EMAIL_LOGO_URL="")
def test_sans_logo_le_nom_seul():
    spec = CATALOGUE[0]
    rendu = email_render(template=spec.template, context=spec.contexte())
    assert "<img" not in rendu.html
    assert "Jàngu Bi</span>" in rendu.html


# --- Mise en ligne du CSS -----------------------------------------------------------------


def test_css_inline_applique_les_regles_dans_l_ordre_et_respecte_le_style_existant():
    html = (
        "<html><head><style data-inline>p { color: red; margin: 0 } .x { color: blue } .x a { color: green }</style>"
        "<style>@media (prefers-color-scheme: dark) { .x { color: white !important } }</style></head>"
        '<body><p class="x">a <a href="#">b</a></p><p class="x" style="color: black">c</p></body></html>'
    )
    out = css_inline(html)
    assert "data-inline" not in out
    assert "prefers-color-scheme" in out  # les requêtes média restent dans l'en-tête
    assert '<p class="x" style="color: blue; margin: 0">' in out
    assert '<a href="#" style="color: green">' in out
    assert '<p class="x" style="color: black; margin: 0">' in out


def test_css_inline_sans_bloc_ne_touche_a_rien():
    html = "<p>Bonjour</p>"
    assert css_inline(html) == html


def test_filtre_fcfa():
    tpl = Template("{% load emails_extras %}{{ a|fcfa }}|{{ b|fcfa }}")
    assert tpl.render(Context({"a": 1500000, "b": "n/a"})) == "1 500 000 FCFA|"


# --- Expéditeur et aperçus ----------------------------------------------------------------


@override_settings(EMAIL_FROM_ADDRESS="noreply@jangubi.sn", EMAIL_FROM_NAME="Jàngu Bi")
def test_expediteur_avec_nom_affiche():
    assert _from_address() == "Jàngu Bi <noreply@jangubi.sn>"


@override_settings(EMAIL_FROM_ADDRESS="Paroisse <p@example.sn>", EMAIL_FROM_NAME="Jàngu Bi")
def test_expediteur_deja_nomme_inchange():
    assert _from_address() == "Paroisse <p@example.sn>"


def test_commande_apercu_emails(tmp_path):
    call_command("apercu_emails", dossier=str(tmp_path))
    for spec in CATALOGUE:
        html = (tmp_path / f"{spec.nom}.html").read_text(encoding="utf-8")
        assert 'src="data:image/png;base64,' in html  # logo intégré : l'aperçu s'affiche hors ligne
        assert (tmp_path / f"{spec.nom}.txt").read_text(encoding="utf-8").startswith("Objet : ")
    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert all(f'href="{spec.nom}.html"' in index for spec in CATALOGUE)
