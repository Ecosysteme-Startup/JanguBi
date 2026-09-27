"""V2 §5.4 : GET platform/dons/activite/ — nombres, taux, délais, incidents ; aucun montant."""

import datetime
from typing import Any

import pytest

from apps.donations.enums import WebhookStatus
from apps.donations.models import Donation, PaymentWebhookEvent
from apps.donations.tests.conftest import client_for

pytestmark = pytest.mark.django_db
URL = "/api/v1/platform/dons/activite/?periode=mois&date=2026-09"
FORBIDDEN = {"montant", "montants", "amount", "total", "collecte", "net", "frais", "fees", "paye", "reuni", "especes",
             "en_ligne", "reverse", "objectif"}  # fmt: skip


def keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys(v)}
    return set()


def test_activity_has_counts_rates_and_delays_but_no_amount(world, sept):
    Donation.objects.filter(pk__in=[d.pk for d in sept.online[:6]]).update(returned_at=datetime.datetime(2026, 9, 20, tzinfo=datetime.UTC))
    PaymentWebhookEvent.objects.create(provider="fake", payload_hash="a" * 64, status=WebhookStatus.TRAITE)
    PaymentWebhookEvent.objects.create(provider="fake", payload_hash="b" * 64, status=WebhookStatus.ERREUR,
                                       error_code="amount_mismatch", external_ref="fake_x")  # fmt: skip
    response = client_for(world.platform).get(URL)
    assert response.status_code == 200, response.json()
    body = response.json()
    assert not keys(body) & FORBIDDEN
    p = body["paiements"]
    assert (p["lances"], p["confirmes"], p["en_attente"], p["echoues"], p["expires"]) == (58, 47, 3, 4, 4)
    assert (p["taux_confirmation"], p["taux_echec"]) == (81, 14)
    assert p["plus_ancien_en_attente"].startswith("2026-09-27T01:00")
    assert body["delais"]["confirmation_mediane_s"] == 41 and body["delais"]["reversement_moyen_jours"] is not None
    assert [(m["moyen"], m["confirmes"]) for m in body["par_moyen"]][:4] == [
        ("wave", 29), ("orange_money", 14), ("free_money", 0), ("carte", 4)
    ]
    sources = {s["source"]: s for s in body["par_source"]}
    assert (sources["app_android"]["confirmes"], sources["web"]["confirmes"], sources["app_ios"]["confirmes"]) == (26, 13, 8)
    assert sum(s["retours"] for s in body["par_source"]) == 6
    names = [row["nom"] for row in body["par_paroisse"]]
    assert names[0] == "Cathédrale Notre-Dame-des-Victoires" and len(names) == 5
    sd = next(row for row in body["par_paroisse"] if row["nom"] == "Saint-Dominique")
    assert (sd["collecte_ouverte"], sd["lances"], sd["confirmes"], sd["quetes_saisies"]) == (True, 58, 47, 10)
    assert body["notifications"]["recues"] == 2 and body["notifications"]["erreurs"] == 1
    assert body["incidents"]["par_type"] == {"amount_mismatch": 1}
    assert len(body["par_jour"]) == 27 and sum(d["lances"] for d in body["par_jour"]) == 58
    assert sum(c["nombre"] for c in body["charge"]) == 58


def test_activity_is_for_the_platform_only(world, sept):
    for user in (world.cure, world.econome_dio, world.eveque, world.fidele):
        assert client_for(user).get(URL).status_code == 403
