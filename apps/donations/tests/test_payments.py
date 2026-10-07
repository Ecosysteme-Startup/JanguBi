"""Paiement en ligne : checkout, webhook signé, idempotence, machine à états, réconciliation."""

import datetime
import logging
import re

import pytest
from django.core import mail
from django.test import override_settings
from django.utils import timezone
from freezegun import freeze_time

from apps.core.exceptions import ApplicationError, ConflictError
from apps.donations import services
from apps.donations.enums import DonationStatus, StatusSource, WebhookStatus
from apps.donations.models import Donation, DonationActivation, DonationStatusChange, PaymentWebhookEvent
from apps.donations.providers.base import ProviderError
from apps.donations.providers.fake import FakeProvider
from apps.donations.tests.conftest import client_for, open_fund, pay
from apps.emails.models import Email

pytestmark = pytest.mark.django_db
S = DonationStatus


def give(fund, amount=5000, **kwargs):
    fields = {"fees_covered": False, "anonymous": False, **kwargs}
    donation, _, _ = services.checkout_create(fund=fund, amount=amount, **fields)
    return donation


# --- Montants -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "amount, covered, expected",
    [(5000, False, (100, 5000, 4900)), (5000, True, (100, 5100, 5000)), (1001, True, (21, 1022, 1001))],
)
def test_fees_are_shown_and_either_added_or_deducted(amount, covered, expected):
    assert services.fees_compute(amount=amount, fees_covered=covered) == expected


@pytest.mark.parametrize("amount", [0, 99, 1_000_001, 5000.5, "5000", True])
def test_amount_must_be_an_integer_within_bounds(fund, amount):
    with pytest.raises(ApplicationError):
        give(fund, amount=amount)


# --- Checkout -------------------------------------------------------------------------------


def test_checkout_creates_a_pending_donation_with_a_payment_url(fund, world):
    donation, attempt, created = services.checkout_create(
        fund=fund, amount=5000, fees_covered=True, anonymous=False, donor=world.fidele
    )
    assert created and donation.status == S.EN_ATTENTE
    assert donation.donor == world.fidele and donation.charged_amount == 5100 and donation.net_amount == 5000
    assert attempt.checkout_url.startswith("https://paiement.exemple.test/checkout/")
    assert attempt.external_ref and re.fullmatch(r"\d{4}-\d{4}-\d{4}", donation.reference)
    assert donation.receipt_number is None  # attribué à la confirmation seulement
    assert list(donation.status_changes.values_list("from_status", "to_status")) == [(S.INITIE, S.EN_ATTENTE)]


def test_logged_in_donor_email_is_never_stored(fund, world):
    donation = give(fund, donor=world.fidele, donor_email="autre@test.sn")
    assert donation.donor_email == ""


def test_minor_donor_is_refused_server_side(fund, world):
    """JB-WEB-014 (RG-13) : un don d'un donateur connecté mineur est refusé par le serveur."""
    from apps.core.exceptions import PermissionDeniedError
    from apps.users.models import Profile

    minor_birth = timezone.localdate().replace(year=timezone.localdate().year - 15)
    Profile.objects.update_or_create(user=world.fidele, defaults={"date_of_birth": minor_birth})
    with pytest.raises(PermissionDeniedError) as exc:
        services.checkout_create(fund=fund, amount=5000, fees_covered=True, anonymous=False, donor=world.fidele)
    assert exc.value.code == "minor"
    assert Donation.objects.count() == 0


def test_adult_donor_is_allowed(fund, world):
    from apps.users.models import Profile

    adult_birth = timezone.localdate().replace(year=timezone.localdate().year - 40)
    Profile.objects.update_or_create(user=world.fidele, defaults={"date_of_birth": adult_birth})
    donation, _, created = services.checkout_create(
        fund=fund, amount=5000, fees_covered=True, anonymous=False, donor=world.fidele
    )
    assert created and donation.status == S.EN_ATTENTE


def test_same_idempotency_key_returns_the_same_donation(fund):
    first, _, created = services.checkout_create(
        fund=fund, amount=2000, fees_covered=False, anonymous=True, idempotency_key="k-1"
    )
    again, _, created_again = services.checkout_create(
        fund=fund, amount=2000, fees_covered=False, anonymous=True, idempotency_key="k-1"
    )
    assert created and not created_again and first.pk == again.pk
    assert Donation.objects.count() == 1
    with pytest.raises(ConflictError):
        services.checkout_create(fund=fund, amount=3000, fees_covered=False, anonymous=True, idempotency_key="k-1")


def test_cannot_give_to_a_closed_draft_or_inactive_fund(world, fund):
    draft = services.fund_create(actor=world.cure, node=world.sd, kind="campagne", title="Brouillon")
    with pytest.raises(ApplicationError):
        give(draft)
    future = open_fund(world, title="Plus tard", starts_on=timezone.localdate() + datetime.timedelta(days=3))
    with pytest.raises(ApplicationError):
        give(future)
    DonationActivation.objects.filter(node=world.sd).update(enabled=False)
    with pytest.raises(ApplicationError) as exc:
        give(fund)
    assert exc.value.code == "donations_disabled"


def test_provider_failure_marks_the_donation_failed(fund, monkeypatch):
    def boom(self, request):
        raise ProviderError("down")

    monkeypatch.setattr(FakeProvider, "create_checkout", boom)
    with pytest.raises(services.ProviderUnavailable):
        give(fund)
    assert Donation.objects.get().status == S.ECHOUE


# --- Webhook --------------------------------------------------------------------------------


def test_signed_webhook_confirms_after_server_side_check(fund, django_capture_on_commit_callbacks):
    donation = give(fund)
    with django_capture_on_commit_callbacks(execute=True):
        response = pay(donation, method="orange_money")
    assert response.status_code == 200
    donation.refresh_from_db()
    assert donation.status == S.CONFIRME and donation.confirmed_at and donation.payment_method == "orange_money"
    assert PaymentWebhookEvent.objects.get().status == WebhookStatus.TRAITE


def test_replayed_webhook_is_counted_once(fund, django_capture_on_commit_callbacks):
    donation = give(fund)
    attempt = donation.attempts.get()
    headers, body = FakeProvider.simulate(attempt.external_ref, "completed")
    kwargs = {f"HTTP_{k.upper().replace('-', '_')}": v for k, v in headers.items()}
    with django_capture_on_commit_callbacks(execute=True):
        for _ in range(3):
            assert client_for().post("/api/v1/dons/webhooks/fake/", data=body, content_type="application/json",
                                     **kwargs).status_code == 200  # fmt: skip
    assert PaymentWebhookEvent.objects.count() == 1
    assert DonationStatusChange.objects.filter(donation=donation, to_status=S.CONFIRME).count() == 1
    # Autre corps pour un don déjà confirmé : doublon, sans effet.
    with django_capture_on_commit_callbacks(execute=True):
        pay(donation, method="wave", fee=90)
    assert PaymentWebhookEvent.objects.filter(status=WebhookStatus.DOUBLON).count() == 1
    assert DonationStatusChange.objects.filter(donation=donation, to_status=S.CONFIRME).count() == 1


def test_invalid_signature_is_rejected_and_changes_nothing(fund):
    donation = give(fund)
    attempt = donation.attempts.get()
    _, body = FakeProvider.simulate(attempt.external_ref, "completed")
    response = client_for().post(
        "/api/v1/dons/webhooks/fake/", data=body, content_type="application/json", HTTP_X_FAKE_SIGNATURE="faux"
    )
    assert response.status_code == 400
    event = PaymentWebhookEvent.objects.get()
    assert event.status == WebhookStatus.REJETE and not event.signature_valid and event.payload == ""
    donation.refresh_from_db()
    assert donation.status == S.EN_ATTENTE


def test_forged_completion_is_not_trusted(fund, django_capture_on_commit_callbacks):
    """La notification dit « payé » mais l'agrégateur, interrogé, dit « en attente »."""
    donation = give(fund)
    attempt = donation.attempts.get()
    headers, body = FakeProvider.simulate(attempt.external_ref, "completed")
    FakeProvider.simulate(attempt.external_ref, "pending")
    with django_capture_on_commit_callbacks(execute=True):
        client_for().post("/api/v1/dons/webhooks/fake/", data=body, content_type="application/json",
                          **{f"HTTP_{k.upper().replace('-', '_')}": v for k, v in headers.items()})  # fmt: skip
    donation.refresh_from_db()
    assert donation.status == S.EN_ATTENTE


def test_amount_mismatch_leaves_the_donation_pending(fund, django_capture_on_commit_callbacks):
    donation = give(fund)
    with django_capture_on_commit_callbacks(execute=True):
        pay(donation, amount=100)
    donation.refresh_from_db()
    assert donation.status == S.EN_ATTENTE
    event = PaymentWebhookEvent.objects.get()
    assert event.status == WebhookStatus.ERREUR and event.error_code == "amount_mismatch"


def test_failed_and_unknown_payments(fund, django_capture_on_commit_callbacks):
    donation = give(fund)
    with django_capture_on_commit_callbacks(execute=True):
        pay(donation, status="failed")
    donation.refresh_from_db()
    assert donation.status == S.ECHOUE
    headers, body = FakeProvider.simulate("fake_inconnu", "completed", amount=5000)
    with django_capture_on_commit_callbacks(execute=True):
        client_for().post("/api/v1/dons/webhooks/fake/", data=body, content_type="application/json",
                          **{f"HTTP_{k.upper().replace('-', '_')}": v for k, v in headers.items()})  # fmt: skip
    assert PaymentWebhookEvent.objects.get(external_ref="fake_inconnu").error_code == "unknown_reference"


def test_webhook_of_another_provider_is_404(fund):
    assert (
        client_for().post("/api/v1/dons/webhooks/paydunya/", data=b"{}", content_type="application/json").status_code
        == 404
    )


def test_real_fee_reported_by_the_provider_is_kept(fund, django_capture_on_commit_callbacks):
    donation = give(fund, amount=10000)
    with django_capture_on_commit_callbacks(execute=True):
        pay(donation, fee=150)
    donation.refresh_from_db()
    assert (donation.fee_amount, donation.net_amount) == (150, 9850)


# --- Machine à états ------------------------------------------------------------------------


def test_state_machine_is_strict(fund, world, django_capture_on_commit_callbacks):
    donation = give(fund)
    with pytest.raises(ApplicationError):
        services.donation_transition(donation=donation, to=S.REMBOURSE, source=StatusSource.STAFF)
    with django_capture_on_commit_callbacks(execute=True):
        pay(donation)
    with pytest.raises(ApplicationError):
        services.donation_transition(donation=donation, to=S.ECHOUE, source=StatusSource.STAFF)
    refunded = services.donation_refund(donation=donation, actor=world.econome, note="erreur de montant")
    assert refunded.status == S.REMBOURSE
    with pytest.raises(ApplicationError):
        services.donation_refund(donation=refunded, actor=world.econome)


# --- Réconciliation -------------------------------------------------------------------------


def test_reconciliation_confirms_then_expires(fund):
    with freeze_time("2026-09-27 09:00:00"):
        paid = give(fund)
        forgotten = give(fund, amount=2000)
        FakeProvider.simulate(paid.attempts.get().external_ref, "completed")
    with freeze_time("2026-09-27 09:30:00"):
        counts = services.donations_reconcile()
    assert counts["confirmes"] == 1
    paid.refresh_from_db()
    forgotten.refresh_from_db()
    assert paid.status == S.CONFIRME and forgotten.status == S.EN_ATTENTE
    with freeze_time("2026-09-28 10:00:00"):
        services.donations_reconcile()
    forgotten.refresh_from_db()
    assert forgotten.status == S.EXPIRE


def test_payment_after_expiry_is_an_incident_not_a_confirmation(fund, django_capture_on_commit_callbacks):
    donation = give(fund)
    services.donation_transition(donation=donation, to=S.EXPIRE, source=StatusSource.RECONCILIATION)
    with django_capture_on_commit_callbacks(execute=True):
        pay(donation)
    donation.refresh_from_db()
    assert donation.status == S.EXPIRE
    assert PaymentWebhookEvent.objects.get().error_code == "late_payment"


# --- Données personnelles -------------------------------------------------------------------


def test_guest_receipt_email_then_address_purged(fund, django_capture_on_commit_callbacks):
    donation = give(fund, donor_email="Invite@Test.sn")
    assert donation.donor_email == "invite@test.sn"
    with django_capture_on_commit_callbacks(execute=True):
        pay(donation)
    email = Email.objects.get(to="invite@test.sn")
    assert donation.reference in email.plain_text and "pas un reçu fiscal" in email.plain_text
    assert len(mail.outbox) == 1
    assert services.donor_emails_purge() == 0
    with freeze_time(timezone.now() + datetime.timedelta(days=91)):
        assert services.donor_emails_purge() == 1
    donation.refresh_from_db()
    assert donation.donor_email == ""


def test_no_amount_name_or_email_in_logs(fund, world, caplog, django_capture_on_commit_callbacks):
    caplog.set_level(logging.DEBUG, logger="apps.donations")
    donation = give(fund, amount=7777, donor_email="secret@test.sn")
    with django_capture_on_commit_callbacks(execute=True):
        pay(donation, amount=1)  # incohérence : journalisée par référence seulement
    text = caplog.text
    assert "7777" not in text and "secret@test.sn" not in text and "Diop" not in text


@override_settings(DONATIONS_CHECKOUT_THROTTLE_RATE="2/hour")
def test_public_checkout_is_rate_limited(fund):
    client = client_for()
    body = {"fund_id": str(fund.pk), "amount": 1000}
    assert client.post("/api/v1/dons/checkout/", body, format="json").status_code == 201
    assert client.post("/api/v1/dons/checkout/", body, format="json").status_code == 201
    assert client.post("/api/v1/dons/checkout/", body, format="json").status_code == 429


# --- Numérotation des reçus et clôture des campagnes (décisions du 27/09/2026) --------------


def test_receipt_numbers_are_sequential_per_parish_without_gaps(fund, world, django_capture_on_commit_callbacks):
    failed = give(fund)
    first, second = give(fund, amount=2000), give(fund, amount=3000)
    with django_capture_on_commit_callbacks(execute=True):
        pay(failed, status="failed")
        pay(second)
        pay(first)
    for d in (failed, first, second):
        d.refresh_from_db()
    year = timezone.localdate().year
    assert failed.receipt_number is None
    assert (second.receipt_number, first.receipt_number) == (f"SD-{year}-00001", f"SD-{year}-00002")
    services.donation_refund(donation=first, actor=world.econome)
    first.refresh_from_db()
    assert first.receipt_number == f"SD-{year}-00002"  # un remboursement ne libère pas le numéro


def test_campaign_closes_when_goal_is_reached(world, django_capture_on_commit_callbacks):
    campaign = open_fund(world, kind="campagne", title="Toiture", goal_amount=9_000)
    first = give(campaign, amount=5000, fees_covered=True)
    with django_capture_on_commit_callbacks(execute=True):
        pay(first)
    campaign.refresh_from_db()
    assert campaign.status == "ouvert"
    second = give(campaign, amount=5000, fees_covered=True)
    with django_capture_on_commit_callbacks(execute=True):
        pay(second)
    campaign.refresh_from_db()
    assert campaign.status == "clos" and campaign.closed_at
    with pytest.raises(ApplicationError):
        give(campaign)
