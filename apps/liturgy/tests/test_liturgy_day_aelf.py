"""Jour liturgique en mode ``aelf`` : la réponse AELF est servie telle quelle."""

import copy
import datetime
import os

import pytest
from rest_framework.test import APIClient

from apps.liturgy.selectors import liturgy_day
from apps.liturgy.tests.factories import LiturgicalDateFactory, ReadingFactory

pytestmark = pytest.mark.django_db
DAY = datetime.date(2026, 10, 4)

# FIXTURE DE TEST : objets « lectures » au format de https://api.aelf.org/v1/messes/{date}/{zone}.
TEST_FIXTURE_AELF_LECTURES = [
    {
        "type": "lecture_1",
        "ref": "Ha 1, 2-3 ; 2, 2-4",
        "titre": "« Le juste vivra par sa fidélité »",
        "intro_lue": "Lecture du livre du prophète Habacuc",
        "contenu": "<p>Combien de temps, Seigneur, vais-je appeler…</p>",
    },
    {
        "type": "psaume",
        "ref": "94 (95), 1-2, 6-7ab, 7d-8a.9",
        "refrain_psalmique": "<p>Aujourd’hui, ne fermez pas votre cœur,<br />mais écoutez la voix du Seigneur.</p>",
        "ref_refrain": "cf. 94, 8a.7d",
        "contenu": "<p>Venez, crions de joie pour le Seigneur…</p>",
    },
    {
        "type": "lecture_2",
        "ref": "2 Tm 1, 6-8.13-14",
        "titre": "« N’aie pas honte de rendre témoignage à notre Seigneur »",
        "intro_lue": "Lecture de la deuxième lettre de saint Paul apôtre à Timothée",
        "contenu": "<p>Bien-aimé, je te le rappelle…</p>",
    },
    {
        "type": "evangile",
        "ref": "Lc 17, 5-10",
        "titre": "« Si vous aviez de la foi ! »",
        "intro_lue": "Évangile de Jésus Christ selon saint Luc",
        "verset_evangile": "<p>La parole du Seigneur demeure pour toujours…</p>",
        "ref_verset": "1 P 1, 25",
        "contenu": "<p>En ce temps-là, les Apôtres dirent au Seigneur…</p>",
    },
]


@pytest.fixture
def aelf_day():
    date_obj = LiturgicalDateFactory(date=DAY, zone="afrique")
    for lec in copy.deepcopy(TEST_FIXTURE_AELF_LECTURES):
        ReadingFactory(
            liturgical_date=date_obj, type=lec["type"], citation=lec["ref"], text=lec["contenu"], raw_metadata=lec
        )
    return date_obj


@pytest.mark.skipif("LITURGY_SOURCE" in os.environ, reason="LITURGY_SOURCE forcé par l'environnement")
def test_aelf_is_default_source():
    from django.conf import settings as django_settings

    assert django_settings.LITURGY_SOURCE == "aelf"


def test_aelf_mode_passes_lectures_through_unchanged(aelf_day, settings):
    settings.LITURGY_SOURCE = "aelf"
    data = liturgy_day(day=DAY)
    assert data["readings_available"] is True
    assert data["edition"] is None and "AELF" in data["notice"]
    assert [r["type"] for r in data["readings"]] == ["lecture_1", "psaume", "lecture_2", "evangile"]
    for served, lec in zip(data["readings"], TEST_FIXTURE_AELF_LECTURES, strict=True):
        assert served == {
            "type": lec["type"],
            "citation": lec["ref"],
            "text": lec["contenu"],
            "verses": [],
            "aelf": lec,
        }


def test_aelf_mode_empty_raw_metadata_is_not_fabricated(settings):
    settings.LITURGY_SOURCE = "aelf"
    date_obj = LiturgicalDateFactory(date=DAY, zone="afrique")
    ReadingFactory(liturgical_date=date_obj, type="evangile", citation="Lc 17, 5-10", text="<p>x</p>", raw_metadata={})
    assert liturgy_day(day=DAY)["readings"][0]["aelf"] == {}


def test_crampon_refs_mode_has_no_aelf_object(aelf_day, settings):
    settings.LITURGY_SOURCE = "crampon_refs"
    data = liturgy_day(day=DAY)
    assert all(r["aelf"] is None and r["text"] is None for r in data["readings"])
    assert "Habacuc" not in str(data)


def test_api_aelf_mode_payload(aelf_day, settings):
    settings.LITURGY_SOURCE = "aelf"
    response = APIClient().get(f"/api/v1/liturgy/{DAY.isoformat()}/")
    assert response.status_code == 200
    assert response.json()["readings"][3]["aelf"] == TEST_FIXTURE_AELF_LECTURES[3]
