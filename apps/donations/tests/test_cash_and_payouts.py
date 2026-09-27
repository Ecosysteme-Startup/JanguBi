"""Quêtes en espèces (deux compteurs, validation par une seconde personne) et reversements (H1)."""

import datetime

import pytest
from django.utils import timezone

from apps.core.exceptions import ApplicationError, PermissionDeniedError
from apps.donations import services
from apps.donations.enums import CashCollectionStatus, DonationChannel, DonationStatus, PayoutStatus
from apps.donations.models import Donation, Payout
from apps.donations.providers.base import PayoutData
from apps.donations.providers.fake import FakeProvider
from apps.donations.tests.conftest import pay

pytestmark = pytest.mark.django_db
YESTERDAY = datetime.date.today() - datetime.timedelta(days=1)


def collect(world, fund, **kwargs):
    fields = {
        "actor": world.secretaire,
        "node": world.sd,
        "fund": fund,
        "mass_date": YESTERDAY,
        "mass_label": "Messe de 10 h",
        "amount": 187_500,
        "counter_one": "Pierre Gomis",
        "counter_two": "Thérèse Sagna",
        **kwargs,
    }
    return services.cash_collection_create(**fields)


def test_cash_collection_is_validated_by_another_person(world, fund):
    collection = collect(world, fund, place=world.place, observation="Billets et pièces")
    assert collection.status == CashCollectionStatus.SAISIE
    assert not Donation.objects.exists()
    with pytest.raises(ApplicationError) as exc:
        services.cash_collection_validate(collection=collection, actor=world.secretaire)
    assert exc.value.code == "four_eyes"
    services.cash_collection_validate(collection=collection, actor=world.econome)
    donation = Donation.objects.get()
    assert donation.channel == DonationChannel.ESPECES and donation.status == DonationStatus.CONFIRME
    assert donation.net_amount == 187_500 and donation.anonymous and donation.fee_amount == 0
    with pytest.raises(ApplicationError):
        services.cash_collection_validate(collection=collection, actor=world.cure)


@pytest.mark.parametrize(
    "overrides, code",
    [
        ({"counter_two": "pierre gomis"}, "two_counters_required"),
        ({"counter_two": " "}, "two_counters_required"),
        ({"amount": 0}, "invalid_amount"),
        ({"mass_date": datetime.date.today() + datetime.timedelta(days=2)}, "future_mass"),
    ],
)
def test_cash_collection_rules(world, fund, overrides, code):
    with pytest.raises(ApplicationError) as exc:
        collect(world, fund, **overrides)
    assert exc.value.code == code


def test_cash_collection_permissions_and_rejection(world, fund):
    with pytest.raises(PermissionDeniedError):
        collect(world, fund, actor=world.fidele)
    with pytest.raises(PermissionDeniedError):
        collect(world, fund, actor=world.eveque)  # droit hérité du diocèse : pas de saisie
    collection = collect(world, fund)
    with pytest.raises(ApplicationError):
        services.cash_collection_reject(collection=collection, actor=world.cure, reason=" ")
    rejected = services.cash_collection_reject(collection=collection, actor=world.cure, reason="Recompter")
    assert rejected.status == CashCollectionStatus.REJETEE and not Donation.objects.exists()


def test_cash_fund_must_belong_to_the_parish(world, fund):
    other = services.fund_create(actor=world.autre_cure, node=world.st, kind="quete_dominicale", title="ST")
    services.fund_publish(fund=other, actor=world.autre_cure)
    with pytest.raises(ApplicationError):
        collect(world, other)
    with pytest.raises(ApplicationError):
        collect(world, fund, place=_place(world))


def _place(world):
    from apps.hierarchy.tests.factories import make_place

    return make_place(world.st, "Église Sainte-Thérèse")


# --- Reversements -------------------------------------------------------------------------


def _confirmed(fund, amount, django_capture_on_commit_callbacks):
    donation, _, _ = services.checkout_create(fund=fund, amount=amount, fees_covered=False, anonymous=False)
    with django_capture_on_commit_callbacks(execute=True):
        pay(donation)
    donation.refresh_from_db()
    return donation


def test_payout_is_recorded_at_the_diocese_and_reconciled(world, fund, django_capture_on_commit_callbacks):
    a = _confirmed(fund, 5000, django_capture_on_commit_callbacks)
    b = _confirmed(fund, 2000, django_capture_on_commit_callbacks)
    lines = [(a.attempts.get().external_ref, 5000, 100), (b.attempts.get().external_ref, 2000, 40)]
    FakeProvider.add_payout(PayoutData("PO-1", timezone.now(), 7000, 140, 6860, lines))
    assert services.payouts_sync() == 1
    assert services.payouts_sync() == 0  # idempotent
    payout = Payout.objects.get()
    assert payout.node == world.dakar and payout.status == PayoutStatus.RAPPROCHE
    assert set(Donation.objects.filter(payout=payout).values_list("pk", flat=True)) == {a.pk, b.pk}


def test_payout_discrepancy_is_flagged(world, fund, django_capture_on_commit_callbacks):
    a = _confirmed(fund, 5000, django_capture_on_commit_callbacks)
    lines = [(a.attempts.get().external_ref, 5000, 100), ("fake_inconnu", 3000, 60)]
    FakeProvider.add_payout(PayoutData("PO-2", timezone.now(), 8000, 160, 7840, lines))
    services.payouts_sync()
    payout = Payout.objects.get()
    assert payout.status == PayoutStatus.ECART and payout.unmatched_count == 1
    assert payout.discrepancy_amount == 7840 - 4900


def test_payout_without_known_transaction_is_skipped(world):
    FakeProvider.add_payout(PayoutData("PO-3", timezone.now(), 1000, 20, 980, [("fake_x", 1000, 20)]))
    assert services.payouts_sync() == 0
