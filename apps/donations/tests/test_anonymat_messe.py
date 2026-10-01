"""V2 §5.6 : anonymat partiel (consultation journalisée) et option « messe anticipée incluse »."""

import datetime

import pytest

from apps.core.exceptions import ApplicationError, PermissionDeniedError
from apps.donations import services
from apps.donations.models import Fund
from apps.donations.tests.conftest import client_for, pay
from apps.hierarchy.models import AuditEvent

pytestmark = pytest.mark.django_db
SUNDAY = datetime.date(2026, 9, 27)
SATURDAY = SUNDAY - datetime.timedelta(days=1)


def anonymous_gift(fund, callbacks, donor):
    donation, _, _ = services.checkout_create(fund=fund, amount=5000, fees_covered=False, anonymous=True, donor=donor)
    with callbacks(execute=True):
        pay(donation)
    return donation


def test_cure_reveals_an_anonymous_donor_with_a_logged_reason(world, fund, django_capture_on_commit_callbacks):
    donation = anonymous_gift(fund, django_capture_on_commit_callbacks, world.fidele)
    url = f"/api/v1/staff/dons/operations/{donation.pk}/donateur/"
    listing = client_for(world.cure).get(f"/api/v1/staff/dons/operations/?node={world.sd.pk}").json()
    assert listing["results"][0]["donor"] == "Anonyme"  # masqué partout ailleurs
    assert client_for(world.cure).post(url, {"motif": "court"}, format="json").status_code == 400
    response = client_for(world.cure).post(url, {"motif": "Remerciement demandé par le conseil"}, format="json")
    assert response.status_code == 200, response.json()
    assert response.json() == {"donation_id": str(donation.pk), "reference": donation.reference, "donateur": "Awa Diop",
                               "sans_compte": False}  # fmt: skip
    event = AuditEvent.objects.get(action="dons.anonymat_consultation")
    assert event.actor == world.cure and event.metadata["motif"] == "Remerciement demandé par le conseil"
    assert event.target_id == str(donation.pk)


def test_only_the_cure_may_reveal(world, fund, django_capture_on_commit_callbacks):
    donation = anonymous_gift(fund, django_capture_on_commit_callbacks, world.fidele)
    for user in (world.econome, world.secretaire, world.autre_cure, world.eveque):
        with pytest.raises(PermissionDeniedError):
            services.donor_reveal(donation=donation, actor=user, reason="Motif suffisamment long")
    assert not AuditEvent.objects.filter(action="dons.anonymat_consultation").exists()


def test_reveal_only_applies_to_anonymous_online_gifts(world, fund, django_capture_on_commit_callbacks):
    donation, _, _ = services.checkout_create(fund=fund, amount=5000, fees_covered=False, anonymous=False)
    with pytest.raises(ApplicationError) as exc:
        services.donor_reveal(donation=donation, actor=world.cure, reason="Motif suffisamment long")
    assert exc.value.code == "not_anonymous"
    no_account = anonymous_gift(fund, django_capture_on_commit_callbacks, None)
    result = services.donor_reveal(donation=no_account, actor=world.cure, reason="Motif suffisamment long")
    assert result["donateur"] is None and result["sans_compte"] is True


@pytest.mark.parametrize("included", [True, False])
def test_anticipated_mass_follows_the_diocese_decision(world, included):
    parent = services.imperee_create(
        actor=world.econome_dio, diocese=world.dakar, title="Grand Séminaire de Brin", starts_on=SUNDAY,
        parishes=[world.sd], messe_anticipee_incluse=included,
    )  # fmt: skip
    assert parent.messe_anticipee_incluse is included
    fund = Fund.objects.get(parent=parent)
    assert fund.messe_anticipee_incluse is included
    kwargs = {"actor": world.secretaire, "node": world.sd, "fund": fund, "mass_label": "Messe anticipée de 18 h 30",
              "amount": 112_500, "counter_one": "A", "counter_two": "B"}  # fmt: skip
    if included:
        assert services.cash_collection_create(mass_date=SATURDAY, **kwargs).pk
    else:
        with pytest.raises(ApplicationError) as exc:
            services.cash_collection_create(mass_date=SATURDAY, **kwargs)
        assert exc.value.code == "mass_outside_imperee"
    with pytest.raises(ApplicationError):
        services.cash_collection_create(mass_date=SUNDAY - datetime.timedelta(days=7), **kwargs)
    proposed = (
        client_for(world.secretaire)
        .get("/api/v1/staff/dons/quetes/fonds-proposes/", {"node": str(world.sd.pk), "date": str(SATURDAY)})
        .json()
    )
    assert any(p["id"] == str(fund.pk) for p in proposed) is included


def test_imperee_api_carries_the_option(world):
    response = client_for(world.econome_dio).post(
        "/api/v1/staff/dons/quetes-imperees/",
        {"node": str(world.dakar.pk), "title": "Brin", "starts_on": "2026-09-27", "parish_ids": [str(world.sd.pk)],
         "messe_anticipee_incluse": True},
        format="json",
    )  # fmt: skip
    assert response.status_code == 201 and response.json()["messe_anticipee_incluse"] is True
