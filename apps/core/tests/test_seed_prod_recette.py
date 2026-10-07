"""seed_prod (données réelles) et seed_recette (recette complète) : ordre des étapes et garde-fous."""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.management.commands import seed_prod, seed_recette


@pytest.fixture
def calls(monkeypatch):
    """Enregistre les sous-commandes au lieu de les lancer."""
    recorded = []

    def fake(name, *args, **kwargs):
        kwargs.pop("stdout", None)
        recorded.append((name, args, kwargs))

    monkeypatch.setattr(seed_prod, "call_command", fake)
    monkeypatch.setattr(seed_recette, "call_command", fake)
    return recorded


@pytest.mark.django_db
def test_seed_prod_only_loads_real_data_and_skips_an_existing_bible(calls, monkeypatch):
    monkeypatch.setattr("apps.bible.seeders.bible_complete", lambda *a: True)

    call_command("seed_prod", hors_ligne=True)

    assert [c[0] for c in calls] == ["seed_hierarchy_profile", "seed_rosary"]
    assert calls[0][1] == ("senegal",)


@pytest.mark.django_db
def test_seed_prod_imports_the_bible_when_missing(calls, monkeypatch):
    monkeypatch.setattr("apps.bible.seeders.bible_complete", lambda *a: False)

    call_command("seed_prod", hors_ligne=True)

    name, args, kwargs = calls[1]
    assert name == "import_bible" and args[0].endswith("bible-fr-aelf.json")


def test_seed_recette_is_refused_without_seed_allowed(calls, monkeypatch):
    monkeypatch.delenv("SEED_ALLOWED", raising=False)
    with pytest.raises(CommandError, match="SEED_ALLOWED"):
        call_command("seed_recette")
    assert calls == []


def test_seed_recette_chains_real_data_demo_and_test_data_with_the_demo_music(calls, monkeypatch):
    monkeypatch.setenv("SEED_ALLOWED", "true")
    monkeypatch.setattr(seed_recette.Command, "_musique_demo", lambda self: "/musique")

    call_command("seed_recette", echelle="petite")

    assert [c[0] for c in calls] == ["seed_prod", "seed_demo", "fetch_seed_assets", "seed_realiste"]
    realiste = calls[-1][2]
    assert realiste["profil"] == "recette" and realiste["medias"] == "complets"
    assert realiste["medias_dossier"] == "/musique" and realiste["verifier"] is True


def test_seed_recette_falls_back_to_light_media_without_the_demo_music(calls, monkeypatch):
    monkeypatch.setenv("SEED_ALLOWED", "true")

    call_command("seed_recette", sans_musique=True, hors_ligne=True)

    assert [c[0] for c in calls] == ["seed_prod", "seed_demo", "seed_realiste"]
    assert calls[-1][2]["medias"] == "legers" and calls[-1][2]["medias_dossier"] is None


def test_seed_recette_reset_removes_only_test_and_demo_data(calls, monkeypatch):
    monkeypatch.setenv("SEED_ALLOWED", "true")

    call_command("seed_recette", reset=True)

    assert [c[0] for c in calls] == ["seed_realiste", "seed_demo"]
    assert all(c[2]["reset"] is True for c in calls)
