"""Contrat HTTP du module dons (cadrage DONS-00 §7) : public, fidèle, paroisse, diocèse, plateforme."""

import datetime
import io
import zipfile

import pytest
from django.utils import timezone

from apps.donations import services
from apps.donations.enums import DonationStatus
from apps.donations.models import Donation, DonationActivation
from apps.donations.tests.conftest import client_for, open_fund, pay

pytestmark = pytest.mark.django_db
TODAY = timezone.localdate()


def confirmed(fund, django_capture_on_commit_callbacks, *, amount=5000, donor=None, anonymous=False):
    donation, _, _ = services.checkout_create(
        fund=fund, amount=amount, fees_covered=False, anonymous=anonymous, donor=donor
    )
    with django_capture_on_commit_callbacks(execute=True):
        pay(donation)
    donation.refresh_from_db()
    return donation


# --- Public -------------------------------------------------------------------------------


def test_public_parish_page(world, fund):
    campaign = open_fund(world, kind="campagne", title="Toiture de la chapelle", goal_amount=4_500_000)
    services.fund_create(actor=world.cure, node=world.sd, kind="campagne", title="Brouillon invisible")
    body = client_for().get(f"/api/v1/public/dons/paroisses/{world.sd.pk}/").json()
    assert body["enabled"] is True
    assert body["authorization"]["reference"] == "ARCH-DAK-2026-041"
    assert "ARCH-DAK-2026-041" in body["authorization"]["text"]
    assert body["suggested_amounts"] == [1000, 2000, 5000, 10000]
    assert {f["id"] for f in body["funds"]} == {str(fund.pk), str(campaign.pk)}
    assert all("donor" not in f for f in body["funds"])


def test_public_page_of_an_inactive_parish_has_no_fund(world):
    body = client_for().get(f"/api/v1/public/dons/paroisses/{world.st.pk}/").json()
    assert body["enabled"] is False and body["funds"] == [] and body["authorization"] is None
    assert client_for().get(f"/api/v1/public/dons/paroisses/{world.dakar.pk}/").status_code == 400


def test_public_fund_detail_with_raised_amount_and_news(world, django_capture_on_commit_callbacks):
    campaign = open_fund(world, kind="campagne", title="Toiture", goal_amount=1_000_000)
    services.fund_news_post(fund=campaign, actor=world.cure, body="Merci : la charpente est commandée.")
    confirmed(campaign, django_capture_on_commit_callbacks, amount=10_000)
    body = client_for().get(f"/api/v1/public/dons/fonds/{campaign.pk}/").json()
    assert body["raised"] == 9800 and body["goal_amount"] == 1_000_000
    assert body["updates"][0]["author_name"] == "Joseph Sarr"
    assert body["parish"]["name"] == "Saint-Dominique"


def test_checkout_api_without_account_then_status(world, fund):
    response = client_for().post(
        "/api/v1/dons/checkout/",
        {"fund_id": str(fund.pk), "amount": 5000, "fees_covered": True, "anonymous": True, "email": "x@test.sn"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="abc",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["charged_amount"] == 5100 and body["checkout_url"].startswith("https://")
    again = client_for().post(
        "/api/v1/dons/checkout/", {"fund_id": str(fund.pk), "amount": 5000, "fees_covered": True, "anonymous": True},
        format="json", HTTP_IDEMPOTENCY_KEY="abc",
    )  # fmt: skip
    assert again.status_code == 200 and again.json()["donation_id"] == body["donation_id"]
    status_body = client_for().get(f"/api/v1/dons/checkout/{body['donation_id']}/").json()
    assert status_body["status"] == DonationStatus.EN_ATTENTE
    assert "email" not in status_body and "donor" not in status_body


def test_checkout_api_errors(world, fund):
    client = client_for()
    bad_amount = client.post("/api/v1/dons/checkout/", {"fund_id": str(fund.pk), "amount": 50}, format="json")
    assert bad_amount.status_code == 400 and bad_amount.json()["error"]["code"] == "amount_out_of_range"
    DonationActivation.objects.filter(node=world.sd).update(enabled=False)
    assert client.post("/api/v1/dons/checkout/", {"fund_id": str(fund.pk), "amount": 5000}, format="json").status_code == 404


def test_checkout_api_links_the_logged_in_donor(world, fund):
    response = client_for(world.fidele).post(
        "/api/v1/dons/checkout/", {"fund_id": str(fund.pk), "amount": 2000}, format="json"
    )
    assert Donation.objects.get(pk=response.json()["donation_id"]).donor == world.fidele


# --- Fidèle -------------------------------------------------------------------------------


def test_my_donations_summary_and_receipt(world, fund, django_capture_on_commit_callbacks):
    donation = confirmed(fund, django_capture_on_commit_callbacks, donor=world.fidele, anonymous=True)
    services.checkout_create(fund=fund, amount=1000, fees_covered=False, anonymous=False, donor=world.fidele)
    confirmed(fund, django_capture_on_commit_callbacks, donor=world.econome)  # un autre donateur
    client = client_for(world.fidele)
    listing = client.get("/api/v1/me/dons/").json()
    assert listing["count"] == 2
    assert {r["status"] for r in listing["results"]} == {"confirme", "en_attente"}
    summary = client.get(f"/api/v1/me/dons/resume/?year={TODAY.year}").json()
    assert summary["total"] == 5000 and summary["count"] == 1
    receipt = client.get(f"/api/v1/me/dons/{donation.pk}/recu/")
    assert receipt.status_code == 200 and receipt["Content-Type"] == "application/pdf"
    assert b"".join(receipt.streaming_content if receipt.streaming else [receipt.content]).startswith(b"%PDF")
    pending = Donation.objects.get(donor=world.fidele, status=DonationStatus.EN_ATTENTE)
    assert client.get(f"/api/v1/me/dons/{pending.pk}/recu/").status_code == 404
    other = Donation.objects.get(donor=world.econome)
    assert client.get(f"/api/v1/me/dons/{other.pk}/recu/").status_code == 404
    assert client_for().get("/api/v1/me/dons/").status_code in (401, 403)


# --- Paroisse -----------------------------------------------------------------------------


def test_operations_mask_names_according_to_capability(world, fund, django_capture_on_commit_callbacks):
    confirmed(fund, django_capture_on_commit_callbacks, donor=world.fidele)
    confirmed(fund, django_capture_on_commit_callbacks, donor=world.fidele, anonymous=True, amount=2000)
    confirmed(fund, django_capture_on_commit_callbacks, amount=1000)
    url = f"/api/v1/staff/dons/operations/?node={world.sd.pk}"
    econome = sorted(r["donor"] for r in client_for(world.econome).get(url).json()["results"])
    assert econome == ["Anonyme", "Awa Diop", "Donateur sans compte"]
    secretaire = sorted(r["donor"] for r in client_for(world.secretaire).get(url).json()["results"])
    assert secretaire == ["Anonyme", "Donateur", "Donateur sans compte"]
    assert client_for(world.econome_dio).get(url).status_code == 403
    assert client_for(world.autre_cure).get(url).status_code == 403
    assert client_for(world.fidele).get(url).status_code == 403


def test_summary_of_the_month(world, fund, django_capture_on_commit_callbacks):
    confirmed(fund, django_capture_on_commit_callbacks, amount=10_000)
    collection = services.cash_collection_create(
        actor=world.secretaire, node=world.sd, fund=fund, mass_date=TODAY, mass_label="Messe de 7 h",
        amount=50_000, counter_one="A", counter_two="B",
    )  # fmt: skip
    services.cash_collection_validate(collection=collection, actor=world.cure)
    body = client_for(world.cure).get(f"/api/v1/staff/dons/synthese/?node={world.sd.pk}").json()
    assert (body["total"], body["online"], body["cash"], body["count"]) == (59_800, 9_800, 50_000, 2)
    assert {m["method"] for m in body["by_method"]} == {"wave", "especes"}
    assert body["daily"][0]["total"] == 59_800
    assert body["by_fund"][0]["title"] == "Quête du dimanche 27 septembre"


def test_fund_crud_over_http(world):
    client = client_for(world.cure)
    created = client.post(
        "/api/v1/staff/dons/fonds/",
        {"node": str(world.sd.pk), "kind": "campagne", "title": "Toiture", "goal_amount": 4_500_000},
        format="json",
    )
    assert created.status_code == 201
    fund_id = created.json()["id"]
    assert client.patch(f"/api/v1/staff/dons/fonds/{fund_id}/", {"description": "Tôles"}, format="json").json()[
        "description"
    ] == "Tôles"
    assert client.post(f"/api/v1/staff/dons/fonds/{fund_id}/publier/").json()["status"] == "ouvert"
    assert client.post(f"/api/v1/staff/dons/fonds/{fund_id}/nouvelles/", {"body": "Début"}, format="json").status_code == 201
    listing = client.get(f"/api/v1/staff/dons/fonds/?node={world.sd.pk}").json()
    assert [f["id"] for f in listing] == [fund_id]
    assert client.get(f"/api/v1/staff/dons/fonds/{fund_id}/").status_code == 200
    assert client.post(f"/api/v1/staff/dons/fonds/{fund_id}/clore/").json()["status"] == "clos"
    assert client_for(world.secretaire).post(
        "/api/v1/staff/dons/fonds/", {"node": str(world.sd.pk), "kind": "campagne", "title": "X"}, format="json"
    ).status_code == 403
    imperee = client.post(
        "/api/v1/staff/dons/fonds/", {"node": str(world.sd.pk), "kind": "quete_imperee", "title": "X"}, format="json"
    )
    assert imperee.status_code == 400


def test_cash_collection_over_http(world, fund):
    payload = {
        "node": str(world.sd.pk), "fund_id": str(fund.pk), "place_id": world.place.pk, "mass_date": str(TODAY),
        "mass_label": "Messe de 10 h", "amount": 120_000, "counter_one": "Pierre", "counter_two": "Paul",
    }  # fmt: skip
    created = client_for(world.secretaire).post("/api/v1/staff/dons/quetes/", payload, format="json")
    assert created.status_code == 201 and created.json()["place"] == "Église Saint-Dominique"
    cid = created.json()["id"]
    assert client_for(world.secretaire).post(f"/api/v1/staff/dons/quetes/{cid}/valider/").status_code == 400
    assert client_for(world.econome).post(f"/api/v1/staff/dons/quetes/{cid}/valider/").json()["status"] == "validee"
    listing = client_for(world.secretaire).get(f"/api/v1/staff/dons/quetes/?node={world.sd.pk}").json()
    assert listing["count"] == 1 and listing["results"][0]["validated_by"] == "Anne Mendy"
    second = client_for(world.secretaire).post("/api/v1/staff/dons/quetes/", payload, format="json").json()["id"]
    rejected = client_for(world.cure).post(f"/api/v1/staff/dons/quetes/{second}/rejeter/", {"reason": "Recompter"},
                                           format="json")  # fmt: skip
    assert rejected.json()["status"] == "rejetee"


def test_refund_over_http(world, fund, django_capture_on_commit_callbacks):
    donation = confirmed(fund, django_capture_on_commit_callbacks)
    url = f"/api/v1/staff/dons/operations/{donation.pk}/rembourser/"
    assert client_for(world.secretaire).post(url, {}, format="json").status_code == 403
    assert client_for(world.econome).post(url, {"note": "doublon"}, format="json").json()["status"] == "rembourse"


def test_export_csv_and_xlsx(world, fund, django_capture_on_commit_callbacks):
    confirmed(fund, django_capture_on_commit_callbacks, donor=world.fidele)
    period = f"node={world.sd.pk}&date_from={TODAY - datetime.timedelta(days=1)}&date_to={TODAY}"
    csv = client_for(world.econome).get(f"/api/v1/staff/dons/export/?{period}")
    text = csv.content.decode("utf-8-sig")
    assert csv["Content-Type"].startswith("text/csv") and "Awa Diop" in text and "Référence" in text
    xlsx = client_for(world.cure).get(f"/api/v1/staff/dons/export/?{period}&fichier=xlsx")
    sheet = zipfile.ZipFile(io.BytesIO(xlsx.content)).read("xl/worksheets/sheet1.xml").decode()
    assert "Quête du dimanche 27 septembre" in sheet and "<v>5000</v>" in sheet
    assert client_for(world.secretaire).get(f"/api/v1/staff/dons/export/?{period}").status_code == 403
    assert client_for(world.econome_dio).get(f"/api/v1/staff/dons/export/?{period}").status_code == 403


def test_reconciliation_over_http(world, fund, django_capture_on_commit_callbacks):
    confirmed(fund, django_capture_on_commit_callbacks)
    period = f"node={world.sd.pk}&date_from={TODAY - datetime.timedelta(days=1)}&date_to={TODAY}"
    body = client_for(world.econome).get(f"/api/v1/staff/dons/rapprochement/?{period}").json()
    assert body["online_net"] == 4900 and body["awaiting_payout"] == 4900 and body["issues"] == []
    inverted = f"node={world.sd.pk}&date_from={TODAY}&date_to={TODAY - datetime.timedelta(days=1)}"
    assert client_for(world.econome).get(f"/api/v1/staff/dons/rapprochement/?{inverted}").status_code == 400


# --- Diocèse et plateforme ----------------------------------------------------------------


def test_imperee_over_http_shows_aggregates_only(world, django_capture_on_commit_callbacks):
    client = client_for(world.econome_dio)
    created = client.post(
        "/api/v1/staff/dons/quetes-imperees/",
        {"node": str(world.dakar.pk), "title": "Grand Séminaire de Brin", "starts_on": "2026-09-27",
         "parish_ids": [str(world.sd.pk)]},
        format="json",
    )  # fmt: skip
    assert created.status_code == 201 and created.json()["parishes_count"] == 1
    child = Donation.objects.none()
    from apps.donations.models import Fund

    parish_fund = Fund.objects.get(parent_id=created.json()["id"])
    child = confirmed(parish_fund, django_capture_on_commit_callbacks, donor=world.fidele)
    rows = client.get(f"/api/v1/staff/dons/quetes-imperees/{created.json()['id']}/suivi/").json()
    assert rows == [
        {"fund_id": str(parish_fund.pk), "parish_id": str(world.sd.pk), "parish": "Saint-Dominique",
         "status": "ouvert", "online": child.net_amount, "cash": 0, "count": 1, "total": child.net_amount}
    ]  # fmt: skip
    assert "Diop" not in str(rows)
    listing = client.get(f"/api/v1/staff/dons/quetes-imperees/?node={world.dakar.pk}").json()
    assert listing[0]["raised"] == child.net_amount
    assert client.get(f"/api/v1/staff/dons/reversements/?node={world.dakar.pk}").json()["count"] == 0
    assert client_for(world.cure).get(f"/api/v1/staff/dons/quetes-imperees/?node={world.dakar.pk}").status_code == 403
    assert client.get(f"/api/v1/staff/dons/quetes-imperees/?node={world.sd.pk}").status_code == 400


def test_platform_health_and_activation(world, fund):
    client = client_for(world.platform)
    health = client.get("/api/v1/platform/dons/sante/").json()
    assert health["provider"] == "fake" and health["pending_payments"] == 0
    assert client_for(world.cure).get("/api/v1/platform/dons/sante/").status_code == 403
    response = client.put(
        "/api/v1/platform/dons/activations/",
        {"node": str(world.st.pk), "enabled": True, "authorization_ref": "ARCH-DAK-2026-052"},
        format="json",
    )
    assert response.status_code == 200 and response.json()["enabled"] is True
    assert len(client.get("/api/v1/platform/dons/activations/").json()) == 2
