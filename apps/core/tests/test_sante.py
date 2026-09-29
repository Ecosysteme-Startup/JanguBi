import pytest
from django.test import Client


@pytest.mark.django_db
def test_sante_repond_200_quand_base_et_cache_repondent():
    for chemin in ("/api/health/", "/api/sante/"):
        reponse = Client().get(chemin)
        assert reponse.status_code == 200
        assert reponse.json()["statut"] == "ok"


@pytest.mark.django_db
def test_sante_repond_503_si_la_base_tombe(monkeypatch):
    monkeypatch.setattr("apps.core.sante._base", lambda: False)
    reponse = Client().get("/api/health/")
    assert reponse.status_code == 503
    assert reponse.json()["base"] is False
