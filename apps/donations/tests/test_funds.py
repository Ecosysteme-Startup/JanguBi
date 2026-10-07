"""Fonds, campagnes et quêtes impérées (c. 1267 §3, c. 1266)."""

import datetime

import pytest
from django.db import IntegrityError

from apps.core.exceptions import ApplicationError, PermissionDeniedError
from apps.donations import services
from apps.donations.enums import FundDestination, FundKind, FundStatus
from apps.donations.models import DonationActivation, Fund
from apps.donations.tests.conftest import open_fund
from apps.hierarchy.models import AuditEvent

pytestmark = pytest.mark.django_db


def test_cure_creates_publishes_and_closes_a_campaign(world):
    fund = services.fund_create(
        actor=world.cure,
        node=world.sd,
        kind=FundKind.CAMPAGNE,
        title="Toiture de la chapelle de la Cité universitaire",
        description="Remplacement des tôles et de la charpente.",
        goal_amount=4_500_000,
    )
    assert fund.status == FundStatus.BROUILLON
    assert fund.destination == FundDestination.PAROISSE
    assert fund.decided_by_office == "cure"
    services.fund_publish(fund=fund, actor=world.cure)
    services.fund_news_post(fund=fund, actor=world.cure, body="Les travaux commencent lundi.")
    services.fund_close(fund=fund, actor=world.econome)
    fund.refresh_from_db()
    assert fund.status == FundStatus.CLOS and fund.closed_at
    actions = set(AuditEvent.objects.filter(target_id=str(fund.pk)).values_list("action", flat=True))
    assert {"dons.fonds_creation", "dons.fonds_publication", "dons.campagne_nouvelle", "dons.fonds_cloture"} <= actions


def test_goal_only_for_campaigns(world):
    fund = services.fund_create(
        actor=world.cure, node=world.sd, kind=FundKind.QUETE_DOMINICALE, title="Q", goal_amount=10
    )
    assert fund.goal_amount is None


@pytest.mark.parametrize("who", ["secretaire", "fidele", "autre_cure", "eveque"])
def test_only_parish_managers_create_funds(world, who):
    with pytest.raises(PermissionDeniedError):
        services.fund_create(actor=getattr(world, who), node=world.sd, kind=FundKind.CAMPAGNE, title="X")


def test_parish_cannot_create_an_imperee(world):
    with pytest.raises(ApplicationError) as exc:
        services.fund_create(actor=world.cure, node=world.sd, kind=FundKind.QUETE_IMPEREE, title="X")
    assert exc.value.code == "imperee_from_diocese"


def test_invalid_period_and_closed_fund_edits(world):
    with pytest.raises(ApplicationError):
        services.fund_create(
            actor=world.cure, node=world.sd, kind=FundKind.CAMPAGNE, title="X",
            starts_on=datetime.date(2026, 10, 2), ends_on=datetime.date(2026, 10, 1),
        )  # fmt: skip
    fund = open_fund(world)
    services.fund_update(fund=fund, actor=world.cure, title="Quête du dimanche")
    with pytest.raises(ApplicationError):
        services.fund_update(fund=fund, actor=world.cure, kind="campagne")
    services.fund_close(fund=fund, actor=world.cure)
    with pytest.raises(ApplicationError):
        services.fund_update(fund=fund, actor=world.cure, title="Autre")
    with pytest.raises(ApplicationError):
        services.fund_publish(fund=fund, actor=world.cure)


def test_news_only_on_campaigns(world):
    with pytest.raises(ApplicationError):
        services.fund_news_post(fund=open_fund(world), actor=world.cure, body="x")


def test_imperee_is_declined_per_active_parish_and_goes_to_the_curia(world):
    DonationActivation.objects.create(node=world.st, enabled=True, authorization_ref="R2")
    parent = services.imperee_create(
        actor=world.econome_dio,
        diocese=world.dakar,
        title="Quête impérée pour le Grand Séminaire de Brin",
        starts_on=datetime.date(2026, 9, 27),
    )
    children = Fund.objects.filter(parent=parent)
    assert {c.node_id for c in children} == {world.sd.pk, world.st.pk}
    assert all(c.destination == FundDestination.CURIE and c.status == FundStatus.OUVERT for c in children)
    assert parent.decided_by_office == "econome_diocesain"
    # La paroisse ne modifie pas la quête impérée du diocèse.
    with pytest.raises(ApplicationError):
        services.fund_update(fund=children.get(node=world.sd), actor=world.cure, title="Autre")


def test_imperee_explicit_parishes_must_belong_to_the_diocese(world):
    with pytest.raises(ApplicationError) as exc:
        services.imperee_create(
            actor=world.eveque, diocese=world.dakar, title="X", starts_on=datetime.date(2026, 9, 27),
            parishes=[world.tree.thies_parish],
        )  # fmt: skip
    assert exc.value.code == "parish_outside"
    with pytest.raises(PermissionDeniedError):
        services.imperee_create(actor=world.cure, diocese=world.dakar, title="X", starts_on=datetime.date(2026, 9, 27))


def test_imperee_without_active_parish_is_refused(world):
    with pytest.raises(ApplicationError) as exc:
        services.imperee_create(
            actor=world.eveque, diocese=world.thies, title="X", starts_on=datetime.date(2026, 9, 27)
        )
    assert exc.value.code in {"no_parish", "dons_forbidden"}


def test_database_forbids_an_imperee_for_the_parish(world):
    with pytest.raises(IntegrityError):
        Fund.objects.create(node=world.sd, kind=FundKind.QUETE_IMPEREE, destination=FundDestination.PAROISSE, title="X")


def test_activation_requires_platform_and_written_authorization(world):
    with pytest.raises(PermissionDeniedError):
        services.activation_set(actor=world.cure, node=world.st, enabled=True, authorization_ref="R")
    with pytest.raises(ApplicationError) as exc:
        services.activation_set(actor=world.platform, node=world.st, enabled=True)
    assert exc.value.code == "authorization_required"
    activation = services.activation_set(actor=world.platform, node=world.st, enabled=True, authorization_ref="R")
    assert activation.enabled
    with pytest.raises(ApplicationError):
        services.activation_set(actor=world.platform, node=world.dakar, enabled=False)
