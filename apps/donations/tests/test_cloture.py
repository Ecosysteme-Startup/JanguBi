"""V2 §5.5 : synthèse corrigée, clôture mensuelle (verrou, ajustements) et paiements tardifs persistés."""

import datetime

import pytest
from freezegun import freeze_time

from apps.core.exceptions import ApplicationError, PermissionDeniedError
from apps.donations import selectors, services, services_cloture
from apps.donations.enums import (
    AdjustmentKind,
    DonationStatus,
    IncidentKind,
    IncidentStatus,
    StatusSource,
)
from apps.donations.models import Donation, DonationActivation, DonationAdjustment, MonthClosing, PaymentIncident
from apps.donations.tests.conftest import client_for, pay

pytestmark = pytest.mark.django_db
SEPT = datetime.date(2026, 9, 1)
OCT = datetime.date(2026, 10, 1)


@pytest.fixture(autouse=True)
def _http_before_freeze():
    from apps.donations import apis

    assert apis.SummaryApi is not None  # DRF importé hors du temps figé (quotas)


def give(fund, callbacks, amount=10_000):
    donation, _, _ = services.checkout_create(fund=fund, amount=amount, fees_covered=False, anonymous=False)
    with callbacks(execute=True):
        pay(donation)
    donation.refresh_from_db()
    return donation


def cash(world, fund, mass_date, amount=50_000, label="Messe de 18 h 30"):
    return services.cash_collection_create(
        actor=world.secretaire, node=world.sd, fund=fund, mass_date=mass_date, mass_label=label, amount=amount,
        counter_one="Pierre Gomis", counter_two="Thérèse Sagna",
    )  # fmt: skip


def test_funds_close_past_closes_funds_whose_period_is_over(world):
    """JB-WEB-042 : un fonds ouvert dont ends_on est passé est clôturé automatiquement."""
    from apps.donations.enums import FundStatus
    from apps.donations.models import Fund
    from apps.donations.tests.conftest import open_fund

    today = datetime.date(2026, 10, 6)
    expired = open_fund(
        world, title="Grand Séminaire", starts_on=datetime.date(2026, 9, 27), ends_on=datetime.date(2026, 10, 4)
    )
    current = open_fund(
        world, title="Journée missionnaire", starts_on=datetime.date(2026, 10, 19), ends_on=datetime.date(2026, 10, 26)
    )
    perpetual = open_fund(world, title="Contribution annuelle", starts_on=datetime.date(2026, 1, 1), ends_on=None)

    assert services.funds_close_past(today=today) == 1

    assert Fund.objects.get(pk=expired.pk).status == FundStatus.CLOS
    assert Fund.objects.get(pk=expired.pk).closed_at is not None
    assert Fund.objects.get(pk=current.pk).status == FundStatus.OUVERT  # période à venir : reste ouvert
    assert Fund.objects.get(pk=perpetual.pk).status == FundStatus.OUVERT  # sans date de fin : non touché
    # Idempotent : un second passage ne reclôt rien.
    assert services.funds_close_past(today=today) == 0


# --- Synthèse corrigée ----------------------------------------------------------------------


def test_cash_counts_in_the_month_of_the_mass_not_of_validation(world, fund):
    with freeze_time("2026-09-30 20:00:00"):
        collection = cash(world, fund, datetime.date(2026, 9, 30))
    with freeze_time("2026-10-02 09:00:00"):
        services.cash_collection_validate(collection=collection, actor=world.econome)
        sept = selectors.parish_summary(node=world.sd, month=SEPT)
        octo = selectors.parish_summary(node=world.sd, month=OCT)
    assert (sept["cash"], octo["cash"]) == (50_000, 0)
    assert sept["daily"] == [{"date": datetime.date(2026, 9, 30), "online": 0, "cash": 50_000, "total": 50_000}]


def test_summary_splits_counts_channels_and_destinations(world, fund, django_capture_on_commit_callbacks):
    give(fund, django_capture_on_commit_callbacks)
    services.cash_collection_validate(collection=cash(world, fund, datetime.date.today()), actor=world.econome)
    month = datetime.date.today().strftime("%Y-%m")
    body = client_for(world.cure).get(f"/api/v1/staff/dons/synthese/?node={world.sd.pk}&month={month}").json()
    assert (body["count"], body["online_count"], body["cash_collections_count"]) == (2, 1, 1)
    assert body["daily"][0]["online"] == 9_800 and body["daily"][0]["cash"] == 50_000
    assert body["by_fund"][0]["destination"] == "paroisse"
    assert body["by_destination"] == {"paroisse": 59_800, "curie": 0}
    assert body["closed"] is False and body["pending_oldest_at"] is None


def test_pending_count_is_limited_to_the_month(world, fund):
    donation, _, _ = services.checkout_create(fund=fund, amount=5_000, fees_covered=False, anonymous=False)
    Donation.objects.filter(pk=donation.pk).update(created_at=datetime.datetime(2026, 8, 30, 10, tzinfo=datetime.UTC))
    assert selectors.parish_summary(node=world.sd, month=SEPT)["pending_count"] == 0
    assert selectors.parish_summary(node=world.sd, month=datetime.date(2026, 8, 1))["pending_count"] == 1


# --- Clôture mensuelle ----------------------------------------------------------------------


def test_month_close_freezes_the_month(world, fund, django_capture_on_commit_callbacks):
    with freeze_time("2026-09-20 10:00:00"):
        donation = give(fund, django_capture_on_commit_callbacks)
        services.cash_collection_validate(collection=cash(world, fund, datetime.date(2026, 9, 20)), actor=world.econome)
        with pytest.raises(ApplicationError) as exc:
            services_cloture.month_close(node=world.sd, month=SEPT, actor=world.econome)
        assert exc.value.code == "month_not_over"
    with freeze_time("2026-10-05 10:00:00"):
        with pytest.raises(PermissionDeniedError):
            services_cloture.month_close(node=world.sd, month=SEPT, actor=world.secretaire)
        response = client_for(world.econome).post(
            "/api/v1/staff/dons/clotures/", {"node": str(world.sd.pk), "month": "2026-09"}, format="json"
        )
        assert response.status_code == 201, response.json()
        assert response.json()["totals"]["collecte"] == 60_000
        # Verrou : plus aucune quête datée de septembre.
        with pytest.raises(ApplicationError) as exc:
            cash(world, fund, datetime.date(2026, 9, 27))
        assert exc.value.code == "month_closed"
        # Remboursement en octobre : septembre ne bouge pas, octobre porte la ligne négative.
        services.donation_refund(donation=selectors.operation_get(donation_id=donation.pk), actor=world.econome)
        adjustment = DonationAdjustment.objects.get()
        assert (adjustment.kind, adjustment.amount, adjustment.value_date) == (
            AdjustmentKind.REMBOURSEMENT, -10_000, datetime.date(2026, 10, 5)
        )
        assert selectors.parish_summary(node=world.sd, month=SEPT)["total"] == 59_800
        assert selectors.parish_summary(node=world.sd, month=OCT)["total"] == -9_800
        sept = client_for(world.econome).get(
            "/api/v1/staff/dons/analyse/", {"niveau": "paroisse", "noeud": str(world.sd.pk), "date": "2026-09"}
        ).json()
        assert sept["synthese"]["collecte"] == 60_000
        with pytest.raises(ApplicationError) as exc:
            services_cloture.month_close(node=world.sd, month=SEPT, actor=world.econome)
        assert exc.value.code == "month_already_closed"
        assert client_for(world.cure).get(f"/api/v1/staff/dons/synthese/?node={world.sd.pk}&month=2026-09").json()[
            "closed"
        ] is True


def test_correction_of_a_closed_month_is_an_adjustment_entry(world, fund):
    with freeze_time("2026-10-05 10:00:00"):
        services_cloture.month_close(node=world.sd, month=SEPT, actor=world.econome)
        response = client_for(world.econome).post(
            "/api/v1/staff/dons/ajustements/",
            {"fund_id": str(fund.pk), "channel": "especes", "amount": -2_000, "reason": "Erreur de comptage du 27/09"},
            format="json",
        )
        assert response.status_code == 201, response.json()
        assert response.json()["value_date"] == "2026-10-05" and response.json()["kind"] == "correction"
        assert selectors.parish_summary(node=world.sd, month=OCT)["cash"] == -2_000
        for bad in ({"amount": 0}, {"reason": " "}):
            with pytest.raises(ApplicationError):
                services_cloture.adjustment_create(
                    actor=world.econome, fund=fund, channel="especes", **{"amount": -1, "reason": "x", **bad}
                )


def test_automatic_close_waits_for_the_day_and_for_pending_cash(world, fund):
    with freeze_time("2026-09-27 10:00:00"):
        pending = cash(world, fund, datetime.date(2026, 9, 27))
    with freeze_time("2026-10-09 04:00:00"):
        assert services_cloture.months_auto_close() == 0
    with freeze_time("2026-10-10 04:00:00"):
        assert services_cloture.months_auto_close() == 0  # une quête reste à confirmer
        services.cash_collection_validate(collection=pending, actor=world.econome)
        from apps.donations.tasks import donations_month_close_task

        assert donations_month_close_task() == 1
        assert MonthClosing.objects.get().closed_by is None
        assert services_cloture.months_auto_close() == 0  # idempotente


def test_month_to_close_appears_in_to_do(world, fund):
    DonationActivation.objects.filter(node=world.sd).update(authorization_date=datetime.date(2026, 8, 1))
    with freeze_time("2026-10-03 10:00:00"):
        todo = client_for(world.econome).get(
            "/api/v1/staff/dons/analyse/", {"niveau": "paroisse", "noeud": str(world.sd.pk), "date": "2026-10"}
        ).json()["a_traiter"]
    assert {"type": "cloture_mois", "echeance": "2026-10-10", "objet_id": "2026-09"}.items() <= todo[0].items()


# --- Paiements tardifs persistés ------------------------------------------------------------


def late(world, fund, callbacks):
    donation, _, _ = services.checkout_create(fund=fund, amount=5_000, fees_covered=False, anonymous=False)
    services.donation_transition(donation=donation, to=DonationStatus.EXPIRE, source=StatusSource.RECONCILIATION)
    with callbacks(execute=True):
        pay(donation)
    return donation


def test_late_payment_is_persisted_once_then_integrated(world, fund, django_capture_on_commit_callbacks):
    donation = late(world, fund, django_capture_on_commit_callbacks)
    incident = PaymentIncident.objects.get()
    assert (incident.kind, incident.status, incident.reported_amount) == (IncidentKind.LATE_PAYMENT, "ouvert", 5_000)
    attempt = donation.attempts.get()
    from apps.donations.providers.fake import FakeProvider

    services.payment_state_apply(attempt=attempt, state=FakeProvider().fetch_status(external_ref=attempt.external_ref),
                                 source=StatusSource.RECONCILIATION)  # fmt: skip
    assert PaymentIncident.objects.count() == 1
    todo = client_for(world.econome).get(
        "/api/v1/staff/dons/analyse/", {"niveau": "paroisse", "noeud": str(world.sd.pk)}
    ).json()["a_traiter"]
    assert "paiement_tardif" in [t["type"] for t in todo]
    listing = client_for(world.econome).get(f"/api/v1/staff/dons/incidents/?node={world.sd.pk}").json()
    assert listing[0]["reference"] == donation.reference and listing[0]["donation_status"] == "expire"
    url = f"/api/v1/staff/dons/incidents/{incident.pk}/regulariser/"
    assert client_for(world.secretaire).post(url, {"resolution": "integre"}, format="json").status_code == 403
    response = client_for(world.econome).post(url, {"resolution": "integre", "note": "Débit constaté"}, format="json")
    assert response.status_code == 200, response.json()
    assert response.json()["status"] == IncidentStatus.RESOLU
    donation.refresh_from_db()
    assert donation.status == DonationStatus.CONFIRME and donation.receipt_number and donation.value_date
    assert donation.status_changes.last().note == "paiement tardif intégré"


def test_amount_mismatch_cannot_be_integrated(world, fund, django_capture_on_commit_callbacks):
    donation, _, _ = services.checkout_create(fund=fund, amount=5_000, fees_covered=False, anonymous=False)
    with django_capture_on_commit_callbacks(execute=True):
        pay(donation, amount=4_000)
    incident = PaymentIncident.objects.get()
    assert incident.kind == IncidentKind.AMOUNT_MISMATCH
    with pytest.raises(ApplicationError) as exc:
        services_cloture.incident_resolve(incident=incident, actor=world.econome, resolution="integre")
    assert exc.value.code == "not_a_late_payment"
    services_cloture.incident_resolve(incident=incident, actor=world.econome, resolution="sans_suite")


def test_platform_sees_incidents_without_amount(world, fund, django_capture_on_commit_callbacks):
    donation = late(world, fund, django_capture_on_commit_callbacks)
    body = client_for(world.platform).get("/api/v1/platform/dons/activite/").json()
    assert body["incidents"]["par_type"] == {"late_payment": 1}
    (item,) = body["incidents"]["liste"]
    assert item == {**item, "type": "late_payment", "reference": donation.reference, "paroisse": "Saint-Dominique"}
    assert "5000" not in str(item) and "5 000" not in str(item)
