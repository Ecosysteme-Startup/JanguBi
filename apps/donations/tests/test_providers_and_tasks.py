"""PayDunya (réseau simulé, aucun appel réel), sélection de l'agrégateur, tâches et filtres."""

import datetime
import hashlib
import json
from urllib.parse import urlencode

import pytest
from django.test import override_settings
from django.utils import timezone
from freezegun import freeze_time

from apps.donations import selectors, services, tasks
from apps.donations.enums import DonationStatus, PaymentMethod, WebhookStatus
from apps.donations.models import CashCollection, PaymentWebhookEvent
from apps.donations.providers import get_provider
from apps.donations.providers.base import CheckoutRequest, InvalidSignature, ProviderError, ProviderStatus
from apps.donations.providers.paydunya import PayDunyaProvider
from apps.donations.tests.conftest import pay

KEYS = {"PAYDUNYA_MASTER_KEY": "master", "PAYDUNYA_PRIVATE_KEY": "private", "PAYDUNYA_TOKEN": "token"}
REQUEST = CheckoutRequest(
    reference="4817-2093-6651", amount=5100, description="Don", return_url="https://r", cancel_url="https://c",
    callback_url="https://cb", allocation_key="SD01",
)  # fmt: skip


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


@pytest.fixture
def http(monkeypatch):
    calls = []
    responses = []

    def request(method, url, headers=None, json=None, timeout=None):
        calls.append({"method": method, "url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse(responses.pop(0))

    monkeypatch.setattr("apps.donations.providers.paydunya.requests.request", request)
    return calls, responses


@override_settings(**KEYS)
def test_paydunya_checkout_and_status(http):
    calls, responses = http
    responses.append({"response_code": "00", "response_text": "https://paydunya.com/checkout/abc", "token": "abc"})
    session = PayDunyaProvider().create_checkout(REQUEST)
    assert session.external_ref == "abc" and session.checkout_url.endswith("/abc")
    sent = calls[0]
    assert sent["url"].startswith("https://app.paydunya.com/sandbox-api/v1/checkout-invoice/create")
    assert sent["headers"]["PAYDUNYA-MASTER-KEY"] == "master" and sent["json"]["invoice"]["total_amount"] == 5100
    assert sent["json"]["custom_data"]["allocation_key"] == "SD01" and sent["timeout"]
    responses.append({"status": "completed", "invoice": {"total_amount": "5100"}, "mode": "wave-senegal"})
    state = PayDunyaProvider().fetch_status(external_ref="abc")
    assert (state.status, state.amount, state.method) == (ProviderStatus.COMPLETED, 5100, PaymentMethod.WAVE)
    assert PayDunyaProvider().list_payouts(since=timezone.now()) == []


@override_settings(**KEYS, PAYDUNYA_MODE="live")
def test_paydunya_errors(http):
    calls, responses = http
    responses.append({"response_code": "1001", "response_text": "refus"})
    with pytest.raises(ProviderError):
        PayDunyaProvider().create_checkout(REQUEST)
    assert calls[0]["url"].startswith("https://app.paydunya.com/api/v1/")
    responses.append(ValueError("pas du JSON"))
    with pytest.raises(ProviderError):
        PayDunyaProvider().fetch_status(external_ref="abc")
    responses.append(["liste"])
    with pytest.raises(ProviderError):
        PayDunyaProvider().fetch_status(external_ref="abc")


@override_settings(**KEYS)
def test_paydunya_ipn_form_and_json():
    good = hashlib.sha512(b"master").hexdigest()
    form = urlencode(
        {"data[hash]": good, "data[status]": "completed", "data[invoice][token]": "abc",
         "data[invoice][total_amount]": "5100", "data[mode]": "orange-money-senegal"}
    ).encode()  # fmt: skip
    state = PayDunyaProvider().verify_callback(headers={}, body=form)
    assert (state.external_ref, state.status, state.amount, state.method) == (
        "abc", ProviderStatus.COMPLETED, 5100, PaymentMethod.ORANGE_MONEY
    )
    as_json = json.dumps({"data": {"hash": good, "status": "cancelled", "invoice": {"token": "abc"}}}).encode()
    assert PayDunyaProvider().verify_callback(headers={}, body=as_json).status == ProviderStatus.CANCELLED
    with pytest.raises(InvalidSignature):
        PayDunyaProvider().verify_callback(headers={}, body=b"data[hash]=faux")


def test_paydunya_requires_configuration_and_unknown_provider():
    with pytest.raises(ProviderError):
        PayDunyaProvider()
    with pytest.raises(ProviderError):
        get_provider("inconnu")
    with override_settings(**KEYS):
        assert get_provider("paydunya").code == "paydunya"


# --- Tâches -------------------------------------------------------------------------------


@pytest.mark.django_db
def test_tasks_run_the_services(world, fund):
    donation, _, _ = services.checkout_create(fund=fund, amount=5000, fees_covered=False, anonymous=False)
    assert tasks.donations_reconcile_task() == {"verifies": 0, "confirmes": 0, "expires": 0, "erreurs": 0}
    assert tasks.donations_payouts_sync_task() == 0
    assert tasks.donations_donor_email_purge_task() == 0
    pay(donation)  # hors capture on_commit : l'événement reste « reçu »
    event = PaymentWebhookEvent.objects.get()
    assert tasks.donations_webhook_process_task(event.pk) == WebhookStatus.TRAITE
    assert services.webhook_process(event_id=event.pk).status == WebhookStatus.TRAITE  # déjà traité : inchangé


@pytest.mark.django_db
def test_webhook_process_when_the_provider_is_down(world, fund, monkeypatch):
    donation, _, _ = services.checkout_create(fund=fund, amount=5000, fees_covered=False, anonymous=False)
    pay(donation)
    event = PaymentWebhookEvent.objects.get()

    def down(self, *, external_ref):
        raise ProviderError("down")

    monkeypatch.setattr("apps.donations.providers.fake.FakeProvider.fetch_status", down)
    assert services.webhook_process(event_id=event.pk).error_code == "provider_unavailable"
    with freeze_time(timezone.now() + datetime.timedelta(minutes=20)):
        assert services.donations_reconcile()["erreurs"] == 1


# --- Filtres des sélecteurs -----------------------------------------------------------------


@pytest.mark.django_db
def test_selector_filters(world, fund, django_capture_on_commit_callbacks):
    donation, _, _ = services.checkout_create(
        fund=fund, amount=5000, fees_covered=False, anonymous=False, donor=world.fidele
    )
    with django_capture_on_commit_callbacks(execute=True):
        pay(donation)
    year = timezone.localdate().year
    assert selectors.donations_for_donor(user=world.fidele, fund_id=fund.pk, year=year).count() == 1
    assert selectors.donations_for_donor(user=world.fidele, year=year - 1).count() == 0
    assert selectors.funds_for_parish(node=world.sd, status="ouvert", kind="quete_dominicale").count() == 1
    today = timezone.localdate()
    ops = selectors.operations_for_parish(
        node=world.sd, fund_id=fund.pk, status=DonationStatus.CONFIRME, channel="en_ligne",
        date_from=today, date_to=today,
    )  # fmt: skip
    assert ops.count() == 1
    assert selectors.cash_collections_for_parish(node=world.sd, status="saisie").count() == 0
    assert selectors.export_rows(node=world.sd, date_from=today, date_to=today, fund_id=fund.pk, with_names=False)[0][
        "donateur"
    ] == "Donateur"


@pytest.mark.django_db
def test_reconciliation_issues_and_health(world, fund):
    with freeze_time(timezone.now() - datetime.timedelta(days=10)):
        services.checkout_create(fund=fund, amount=5000, fees_covered=False, anonymous=False)
        CashCollection.objects.create(
            node=world.sd, fund=fund, mass_date=timezone.localdate(), mass_label="Messe", amount=1000,
            counter_one="A", counter_two="B", entered_by=world.secretaire,
        )  # fmt: skip
    today = timezone.localdate()
    report = selectors.parish_reconciliation(node=world.sd, date_from=today - datetime.timedelta(days=30), date_to=today)
    assert {i["kind"] for i in report["issues"]} == {"paiement_en_attente", "quete_non_validee"}
    client_headers = {"HTTP_X_FAKE_SIGNATURE": "faux"}
    from apps.donations.tests.conftest import client_for

    client_for().post("/api/v1/dons/webhooks/fake/", data=b"{}", content_type="application/json", **client_headers)
    health = selectors.platform_health()
    assert health["webhooks_failed_24h"] == 1 and health["pending_payments"] == 1
    assert health["incidents"][0]["error"] == "invalid_signature"
    for missing in ("00000000-0000-0000-0000-000000000000",):
        with pytest.raises(Exception):
            selectors.fund_get(fund_id=missing)
        with pytest.raises(Exception):
            selectors.donation_public_get(donation_id=missing)
        with pytest.raises(Exception):
            selectors.operation_get(donation_id=missing)
        with pytest.raises(Exception):
            selectors.imperee_get(fund_id=missing)
    with pytest.raises(Exception):
        selectors.cash_collection_get(collection_id=0)
    with pytest.raises(Exception):
        selectors.image_get(file_id=0, user=world.cure)


def test_amounts_use_french_non_breaking_spaces():
    from apps.donations.exports import fcfa

    assert fcfa(5000) == "5 000 FCFA"
    assert fcfa(1_250_000, thin=" ") == "1 250 000 FCFA"
