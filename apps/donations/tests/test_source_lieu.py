"""V2 §5.1 : canal d'entrée, lieu de culte, date de valeur, frais réels, retour dans l'app."""

import datetime

import pytest
from django.utils import timezone

from apps.core.exceptions import ApplicationError
from apps.donations import services
from apps.donations.enums import DonationSource
from apps.donations.models import Donation
from apps.donations.tests.conftest import client_for, open_fund, pay
from apps.hierarchy.tests.factories import make_place

pytestmark = pytest.mark.django_db


def test_checkout_records_the_declared_source_and_the_qr_place(world, fund, django_capture_on_commit_callbacks):
    chapelle = make_place(world.sd, "Chapelle de la Cité universitaire")
    response = client_for().post(
        "/api/v1/dons/checkout/",
        {"fund_id": str(fund.pk), "amount": 5000, "source": "app_android", "place_id": chapelle.pk},
        format="json",
    )
    assert response.status_code == 201
    donation = Donation.objects.get(pk=response.json()["donation_id"])
    assert donation.source == DonationSource.APP_ANDROID and donation.place == chapelle
    assert donation.value_date is None  # posée à la confirmation
    with django_capture_on_commit_callbacks(execute=True):
        pay(donation, fee=90)
    donation.refresh_from_db()
    assert donation.value_date == timezone.localdate(donation.confirmed_at)
    assert donation.fee_is_actual is True and donation.fee_amount == 90


def test_source_defaults_to_unknown_and_estimated_fees_are_flagged(world, fund, django_capture_on_commit_callbacks):
    donation, _, _ = services.checkout_create(fund=fund, amount=5000, fees_covered=False, anonymous=False)
    assert donation.source == DonationSource.INCONNU and donation.place is None
    with django_capture_on_commit_callbacks(execute=True):
        pay(donation)
    donation.refresh_from_db()
    assert donation.fee_is_actual is False


def test_online_donation_inherits_the_place_of_its_fund(world):
    chapelle = make_place(world.sd, "Chapelle de la Cité universitaire")
    campaign = open_fund(world, kind="campagne", title="Toiture de la chapelle", goal_amount=4_500_000, place=chapelle)
    donation, _, _ = services.checkout_create(fund=campaign, amount=5000, fees_covered=False, anonymous=False)
    assert donation.place == chapelle
    body = client_for().get(f"/api/v1/public/dons/fonds/{campaign.pk}/").json()
    assert body["place"] == {"id": chapelle.pk, "name": "Chapelle de la Cité universitaire"}


def test_place_of_another_parish_is_refused(world, fund):
    elsewhere = make_place(world.st, "Église Sainte-Thérèse")
    with pytest.raises(ApplicationError) as exc:
        services.checkout_create(fund=fund, amount=5000, fees_covered=False, anonymous=False, place=elsewhere)
    assert exc.value.code == "place_outside"
    with pytest.raises(ApplicationError):
        services.fund_create(actor=world.cure, node=world.sd, kind="campagne", title="X", place=elsewhere)


def test_cash_is_dated_on_the_day_of_the_mass_with_its_place(world, fund):
    sunday = timezone.localdate() - datetime.timedelta(days=7)
    collection = services.cash_collection_create(
        actor=world.secretaire, node=world.sd, fund=fund, mass_date=sunday, mass_label="Messe de 9 h 30",
        amount=96_725, counter_one="Pierre Gomis", counter_two="Thérèse Sagna", place=world.place,
    )  # fmt: skip
    services.cash_collection_validate(collection=collection, actor=world.econome)
    donation = Donation.objects.get()
    assert donation.value_date == sunday and donation.place == world.place and donation.source is None


def test_first_return_on_the_status_page_is_recorded_once(world, fund):
    donation, _, _ = services.checkout_create(fund=fund, amount=5000, fees_covered=False, anonymous=False)
    client_for().get(f"/api/v1/dons/checkout/{donation.pk}/")
    donation.refresh_from_db()
    first = donation.returned_at
    assert first is not None
    client_for().get(f"/api/v1/dons/checkout/{donation.pk}/")
    donation.refresh_from_db()
    assert donation.returned_at == first
