"""V2 §5.2 : dépôt bancaire des espèces et remise à la curie des espèces de quête impérée."""

import datetime

import pytest
from django.utils import timezone

from apps.core.exceptions import ApplicationError, PermissionDeniedError
from apps.donations import selectors, services, services_tresorerie
from apps.donations.enums import RemittanceStatus
from apps.donations.models import CashCollection, Donation, Fund
from apps.donations.tests.conftest import client_for
from apps.hierarchy.models import AuditEvent

pytestmark = pytest.mark.django_db
TODAY = timezone.localdate()
SUNDAY = TODAY - datetime.timedelta(days=(TODAY.isoweekday() % 7))


def validated(world, fund, amount, *, mass_date=SUNDAY, label="Messe de 9 h 30"):
    collection = services.cash_collection_create(
        actor=world.secretaire, node=world.sd, fund=fund, mass_date=mass_date, mass_label=label, amount=amount,
        counter_one="Pierre Gomis", counter_two="Thérèse Sagna",
    )  # fmt: skip
    return services.cash_collection_validate(collection=collection, actor=world.econome)


@pytest.fixture
def imperee(world):
    parent = services.imperee_create(
        actor=world.econome_dio, diocese=world.dakar, title="Quête impérée · Grand Séminaire de Brin",
        starts_on=SUNDAY, parishes=[world.sd],
    )  # fmt: skip
    return Fund.objects.get(parent=parent, node=world.sd)


# --- Dépôt en banque ------------------------------------------------------------------------


def test_deposit_sums_the_validated_collections_once(world, fund):
    a = validated(world, fund, 96_725)
    b = validated(world, fund, 115_775, label="Messe de 11 h 30")
    deposit = services_tresorerie.cash_deposit_declare(
        actor=world.econome, node=world.sd, collection_ids=[a.pk, b.pk], deposited_on=TODAY,
        bank_label="CBAO, compte paroisse", slip_number="BRD-0412",
    )  # fmt: skip
    assert deposit.amount == 212_500
    assert set(CashCollection.objects.filter(deposit=deposit).values_list("pk", flat=True)) == {a.pk, b.pk}
    assert AuditEvent.objects.filter(action="dons.depot_especes").count() == 1
    with pytest.raises(ApplicationError) as exc:
        services_tresorerie.cash_deposit_declare(
            actor=world.econome, node=world.sd, collection_ids=[a.pk], deposited_on=TODAY,
            bank_label="CBAO", slip_number="BRD-0413",
        )  # fmt: skip
    assert exc.value.code == "collection_already_deposited"
    # Un dépôt ne change aucun total collecté.
    assert Donation.objects.count() == 2


def test_deposit_rules(world, fund):
    pending = services.cash_collection_create(
        actor=world.secretaire, node=world.sd, fund=fund, mass_date=SUNDAY, mass_label="Messe de 7 h",
        amount=86_475, counter_one="A", counter_two="B",
    )  # fmt: skip
    kwargs = {"node": world.sd, "deposited_on": TODAY, "bank_label": "CBAO", "slip_number": "X1"}
    with pytest.raises(ApplicationError) as exc:
        services_tresorerie.cash_deposit_declare(actor=world.econome, collection_ids=[pending.pk], **kwargs)
    assert exc.value.code == "collection_not_validated"
    done = validated(world, fund, 1000)
    with pytest.raises(PermissionDeniedError):  # la secrétaire saisit, elle ne dépose pas
        services_tresorerie.cash_deposit_declare(actor=world.secretaire, collection_ids=[done.pk], **kwargs)
    with pytest.raises(ApplicationError) as exc:
        services_tresorerie.cash_deposit_declare(
            actor=world.econome,
            collection_ids=[done.pk],
            **{**kwargs, "deposited_on": SUNDAY - datetime.timedelta(days=1)},
        )
    assert exc.value.code == "deposit_before_mass"


def test_deposit_over_http(world, fund):
    a = validated(world, fund, 212_500)
    url = "/api/v1/staff/dons/depots/"
    created = client_for(world.econome).post(
        url, {"node": str(world.sd.pk), "collection_ids": [a.pk], "deposited_on": str(TODAY),
              "bank_label": "CBAO", "slip_number": "BRD-0412"}, format="json",
    )  # fmt: skip
    assert created.status_code == 201, created.json()
    assert created.json()["amount"] == 212_500 and created.json()["collections_count"] == 1
    listing = client_for(world.cure).get(f"{url}?node={world.sd.pk}").json()
    assert listing["count"] == 1
    assert client_for(world.autre_cure).get(f"{url}?node={world.sd.pk}").status_code == 403


# --- Remise à la curie ----------------------------------------------------------------------


def test_imperee_has_a_default_remittance_deadline(imperee):
    assert imperee.remit_by == SUNDAY + datetime.timedelta(days=7)
    assert imperee.parent.remit_by == imperee.remit_by


def test_remittance_declared_by_parish_and_confirmed_by_curia(world, imperee):
    validated(world, imperee, 646_000)
    remittance = services_tresorerie.curia_remittance_declare(
        actor=world.econome, fund=imperee, amount=646_000, remitted_on=TODAY, reference="Reçu curie 2026-118"
    )
    assert remittance.status == RemittanceStatus.DECLAREE
    with pytest.raises(ApplicationError) as exc:
        services_tresorerie.curia_remittance_declare(actor=world.econome, fund=imperee, amount=1, remitted_on=TODAY)
    assert exc.value.code == "remittance_exceeds_cash"
    with pytest.raises(PermissionDeniedError):  # la paroisse ne confirme pas sa propre remise
        services_tresorerie.curia_remittance_confirm(remittance=remittance, actor=world.cure)
    remittance = services_tresorerie.curia_remittance_confirm(remittance=remittance, actor=world.econome_dio)
    assert remittance.status == RemittanceStatus.CONFIRMEE and remittance.confirmed_by == world.econome_dio
    # Aucun don n'est créé au diocèse (pas de double compte).
    assert not Donation.objects.filter(fund__node=world.dakar).exists()
    row = selectors.imperee_follow(fund=imperee.parent)[0]
    assert (row["cash"], row["remitted_confirmed"], row["to_remit"]) == (646_000, 646_000, 0)


def test_contested_remittance_frees_the_amount(world, imperee):
    validated(world, imperee, 100_000)
    remittance = services_tresorerie.curia_remittance_declare(
        actor=world.econome, fund=imperee, amount=100_000, remitted_on=TODAY
    )
    with pytest.raises(ApplicationError):
        services_tresorerie.curia_remittance_contest(remittance=remittance, actor=world.eveque, reason=" ")
    services_tresorerie.curia_remittance_contest(remittance=remittance, actor=world.eveque, reason="Montant non reçu")
    again = services_tresorerie.curia_remittance_declare(
        actor=world.econome, fund=imperee, amount=100_000, remitted_on=TODAY
    )
    assert again.status == RemittanceStatus.DECLAREE


def test_remittance_only_for_an_imperee_declination(world, fund):
    with pytest.raises(ApplicationError) as exc:
        services_tresorerie.curia_remittance_declare(actor=world.econome, fund=fund, amount=1, remitted_on=TODAY)
    assert exc.value.code == "not_an_imperee"


def test_remittances_over_http(world, imperee):
    validated(world, imperee, 646_000)
    created = client_for(world.econome).post(
        "/api/v1/staff/dons/remises-curie/",
        {"fund_id": str(imperee.pk), "amount": 646_000, "remitted_on": str(TODAY), "mode": "especes"},
        format="json",
    )
    assert created.status_code == 201, created.json()
    rid = created.json()["id"]
    diocese_list = client_for(world.econome_dio).get(f"/api/v1/staff/dons/remises-curie/?node={world.dakar.pk}")
    assert diocese_list.status_code == 200 and diocese_list.json()["results"][0]["parish"] == "Saint-Dominique"
    assert client_for(world.cure).get(f"/api/v1/staff/dons/remises-curie/?node={world.dakar.pk}").status_code == 403
    assert client_for(world.cure).post(f"/api/v1/staff/dons/remises-curie/{rid}/confirmer/").status_code == 403
    confirmed = client_for(world.econome_dio).post(f"/api/v1/staff/dons/remises-curie/{rid}/confirmer/")
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "confirmee"
    follow = client_for(world.econome_dio).get(f"/api/v1/staff/dons/quetes-imperees/{imperee.parent_id}/suivi/").json()
    assert follow[0]["remitted_confirmed"] == 646_000 and follow[0]["remit_by"] == str(imperee.remit_by)
