"""Moteur de capacités : matrice SRS §6.4 et règles de nomination (EF-PER-04 à -09)."""

from datetime import date, timedelta

import pytest
from django.utils import timezone
from freezegun import freeze_time

from apps.core.exceptions import ApplicationError, PermissionDeniedError
from apps.hierarchy import authz
from apps.hierarchy.enums import AssignmentStatus
from apps.hierarchy.models import AuditEvent, Capability, OfficeAssignment
from apps.hierarchy.services_offices import (
    assignment_cancel,
    assignment_create,
    assignment_terminate,
    assignments_sync_statuses,
    capability_override_create,
)
from apps.hierarchy.tests.factories import make_node, nominate, office, person, priest
from apps.users.tests.factories import SuperAdminFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(tree):
    """Dakar : évêque, chancelier, doyen, curé et secrétaire de Saint-Dominique. Thiès : chancelier."""
    tree.eveque = person("eveque@dakar.sn", ordre="eveque")
    tree.chancelier = person("chancelier@dakar.sn")
    tree.chancelier_thies = person("chancelier@thies.sn")
    tree.doyen = priest("doyen@dakar.sn")
    tree.cure = priest("cure@sd.sn")
    tree.secretaire = person("secretaire@sd.sn")
    nominate(tree.eveque, "eveque_diocesain", tree.dakar)
    nominate(tree.chancelier, "chancelier", tree.dakar)
    nominate(tree.chancelier_thies, "chancelier", tree.thies)
    nominate(tree.doyen, "doyen", tree.doyenne)
    nominate(tree.cure, "cure", tree.saint_dominique)
    nominate(tree.secretaire, "secretaire_paroissial", tree.saint_dominique)
    return tree


# --- Matrice SRS §6.4 ----------------------------------------------------------------------


def test_secretary_processes_acts_in_her_parish_only(world):
    assert authz.peut(world.secretaire, "actes.traiter", world.saint_dominique)
    assert not authz.peut(world.secretaire, "actes.traiter", world.sainte_therese)


def test_cure_appoints_a_secretary(world):
    new = person("nouvelle@sd.sn")

    assignment = assignment_create(
        actor=world.cure, person=new, office_type=office("secretaire_paroissial"), node=world.saint_dominique
    )

    assert assignment.status == AssignmentStatus.ACTIVE
    assert authz.peut(new, "actes.traiter", world.saint_dominique)


def test_cure_cannot_appoint_a_vicar(world):
    with pytest.raises(PermissionDeniedError):
        assignment_create(
            actor=world.cure, person=priest(), office_type=office("vicaire_paroissial"), node=world.saint_dominique
        )


def test_chancellor_of_dakar_appoints_in_dakar_not_in_thies(world):
    world.saint_dominique_cure_old = OfficeAssignment.objects.get(person=world.cure)
    assignment_terminate(actor=world.chancelier, assignment=world.saint_dominique_cure_old)

    assignment_create(actor=world.chancelier, person=priest(), office_type=office("cure"), node=world.sainte_therese)
    with pytest.raises(PermissionDeniedError):
        assignment_create(actor=world.chancelier, person=priest(), office_type=office("cure"), node=world.thies_parish)


def test_dean_sees_dashboards_of_his_parishes_but_not_their_files(world):
    assert authz.peut(world.doyen, "tableau_bord.voir", world.saint_dominique)
    assert authz.peut(world.doyen, "actes.superviser", world.saint_dominique)
    assert not authz.peut(world.doyen, "actes.traiter", world.saint_dominique)
    assert not authz.peut(world.doyen, "tableau_bord.voir", world.thies_parish)


def test_ended_assignment_loses_capability_the_next_day(world):
    assignment = OfficeAssignment.objects.get(person=world.secretaire)
    today = timezone.localdate()
    assignment_terminate(actor=world.cure, assignment=assignment, end_date=today + timedelta(days=1))

    assert authz.peut(world.secretaire, "actes.traiter", world.saint_dominique)
    with freeze_time(today + timedelta(days=2)):
        assert not authz.peut(world.secretaire, "actes.traiter", world.saint_dominique)
        assignments_sync_statuses()
    assignment.refresh_from_db()
    assert assignment.status == AssignmentStatus.TERMINEE


def test_manual_termination_is_immediate(world):
    assignment = OfficeAssignment.objects.get(person=world.secretaire)
    assert authz.peut(world.secretaire, "actes.traiter", world.saint_dominique)

    assignment_terminate(actor=world.cure, assignment=assignment)

    assert assignment.status == AssignmentStatus.TERMINEE
    assert not authz.peut(world.secretaire, "actes.traiter", world.saint_dominique)


def test_capability_override_in_thies_has_no_effect_in_dakar(world):
    cure_thies = priest()
    nominate(cure_thies, "cure", world.thies_parish)
    capability_override_create(
        actor=SuperAdminFactory.create(),
        diocese_node=world.thies,
        office_type=office("cure"),
        capability=Capability.objects.get(code="actes.traiter"),
    )

    assert not authz.peut(cure_thies, "actes.traiter", world.thies_parish)
    assert authz.peut(world.cure, "actes.traiter", world.saint_dominique)


# --- Héritage, portée, plateforme ------------------------------------------------------------


def test_inherited_capability_covers_the_subtree(world):
    ceb = make_node("ceb", "CEB Saint-Paul", world.saint_dominique)
    assert authz.peut(world.cure, "annonces.publier", ceb)
    assert authz.peut(world.eveque, "annonces.publier", ceb)


def test_non_inherited_office_stays_on_its_node(world):
    ceb = make_node("ceb", "CEB Saint-Paul", world.saint_dominique)
    catechist = person()
    nominate(catechist, "catechiste", world.saint_dominique)

    assert authz.peut(catechist, "evenements.gerer", world.saint_dominique)
    assert not authz.peut(catechist, "evenements.gerer", ceb)


def test_bishop_has_no_messaging_nor_platform_capability(world):
    assert not authz.peut(world.eveque, "messagerie.recevoir_fideles", world.saint_dominique)
    assert not authz.peut(world.eveque, "plateforme.admin", None)
    assert authz.peut(world.eveque, "actes.traiter", world.saint_dominique)


def test_platform_admin_administers_but_does_not_process_files(world):
    admin = SuperAdminFactory.create()
    assert authz.peut(admin, "structure.gerer", world.thies_parish)
    assert authz.peut(admin, "plateforme.admin", None)
    assert not authz.peut(admin, "actes.traiter", world.saint_dominique)
    assert not authz.peut(admin, "messagerie.recevoir_fideles", world.saint_dominique)


def test_fidele_has_no_capability(world):
    assert authz.capacites(person()) == []


def test_unknown_capability_is_a_programming_error(world):
    with pytest.raises(ValueError):
        authz.peut(world.cure, "actes.tout_faire", world.saint_dominique)


def test_noeuds_autorises_lists_the_subtree(world):
    codes = set(authz.noeuds_autorises(world.chancelier, "structure.gerer").values_list("code", flat=True))
    assert codes == {"T-DAK", "T-PM", "T-SD", "T-ST"}
    assert set(authz.noeuds_autorises(world.cure, "actes.traiter").values_list("code", flat=True)) == {"T-SD"}


def test_me_capacites_lists_inheritance(world):
    rows = [r for r in authz.capacites(world.secretaire) if r["capacite"] == "actes.traiter"]
    assert rows == [
        {
            "capacite": "actes.traiter",
            "node_id": str(world.saint_dominique.pk),
            "node_name": "Saint-Dominique",
            "herite": True,
            "office": "secretaire_paroissial",
            "office_label": "Secrétaire paroissial",
            "node_type": "paroisse",
        }
    ]


def test_peut_is_cached(world, django_assert_num_queries):
    authz.peut(world.cure, "actes.traiter", world.saint_dominique)
    with django_assert_num_queries(0):
        for _ in range(50):
            authz.peut(world.cure, "actes.traiter", world.saint_dominique)


# --- Règles de nomination ---------------------------------------------------------------------


def test_second_active_cure_is_rejected_but_in_solidum_is_allowed(world):
    with pytest.raises(ApplicationError) as exc:
        assignment_create(actor=world.eveque, person=priest(), office_type=office("cure"), node=world.saint_dominique)
    assert exc.value.code == "cardinality_exceeded"

    assignment_create(actor=world.eveque, person=priest(), office_type=office("cure_in_solidum"), node=world.saint_dominique)
    assignment_create(actor=world.eveque, person=priest(), office_type=office("cure_in_solidum"), node=world.saint_dominique)


def test_successor_can_be_appointed_after_the_end_of_the_mandate(world):
    current = OfficeAssignment.objects.get(person=world.cure)
    today = timezone.localdate()
    assignment_terminate(actor=world.eveque, assignment=current, end_date=today + timedelta(days=10))

    successor = assignment_create(
        actor=world.eveque,
        person=priest(),
        office_type=office("cure"),
        node=world.saint_dominique,
        start_date=today + timedelta(days=11),
    )

    assert successor.status == AssignmentStatus.PROPOSEE


def test_order_condition(world):
    with pytest.raises(ApplicationError) as exc:
        assignment_create(actor=world.eveque, person=person(), office_type=office("vicaire_paroissial"), node=world.saint_dominique)
    assert exc.value.code == "order_required"


def test_unverified_priest_cannot_be_appointed(world):
    with pytest.raises(ApplicationError) as exc:
        assignment_create(
            actor=world.eveque, person=priest(verified=False), office_type=office("vicaire_paroissial"), node=world.saint_dominique
        )
    assert exc.value.code == "clerical_status_not_verified"


def test_office_must_match_the_node_type(world):
    with pytest.raises(ApplicationError) as exc:
        assignment_create(
            actor=SuperAdminFactory.create(), person=person(), office_type=office("secretaire_paroissial"), node=world.doyenne
        )
    assert exc.value.code == "office_node_type_mismatch"


def test_bishop_is_appointed_by_the_platform_only(world):
    with pytest.raises(PermissionDeniedError):
        assignment_create(actor=world.eveque, person=person(ordre="eveque"), office_type=office("eveque_auxiliaire"), node=world.dakar)
    assignment_create(
        actor=SuperAdminFactory.create(), person=person(ordre="eveque"), office_type=office("eveque_auxiliaire"), node=world.dakar
    )


def test_a_person_without_offices_nommer_cannot_appoint(world):
    with pytest.raises(PermissionDeniedError):
        assignment_create(
            actor=world.secretaire, person=person(), office_type=office("catechiste"), node=world.saint_dominique
        )


# --- Cycle de vie par dates (§8.2) --------------------------------------------------------


def test_future_assignment_is_proposed_then_activated_by_the_daily_task(world):
    today = timezone.localdate()
    new = person()
    assignment = assignment_create(
        actor=world.cure,
        person=new,
        office_type=office("referent_numerique"),
        node=world.saint_dominique,
        start_date=today + timedelta(days=3),
    )
    assert assignment.status == AssignmentStatus.PROPOSEE
    assert not authz.peut(new, "annonces.publier", world.saint_dominique)

    with freeze_time(today + timedelta(days=3)):
        counts = assignments_sync_statuses()
        assert counts["activated"] == 1
        assert authz.peut(new, "annonces.publier", world.saint_dominique)


def test_proposed_assignment_can_be_cancelled_not_an_active_one(world):
    future = assignment_create(
        actor=world.cure,
        person=person(),
        office_type=office("catechiste"),
        node=world.saint_dominique,
        start_date=timezone.localdate() + timedelta(days=5),
    )
    assert assignment_cancel(actor=world.cure, assignment=future).status == AssignmentStatus.ANNULEE

    with pytest.raises(ApplicationError):
        assignment_cancel(actor=world.cure, assignment=OfficeAssignment.objects.get(person=world.secretaire))


def test_sync_task_terminates_past_assignments(world):
    assignment = nominate(person(), "catechiste", world.saint_dominique, end_date=date(2021, 1, 1))
    counts = assignments_sync_statuses()
    assignment.refresh_from_db()
    assert counts["terminated"] >= 1 and assignment.status == AssignmentStatus.TERMINEE


# --- Audit (EF-PER-11) -------------------------------------------------------------------------


def test_services_write_the_audit_trail(world):
    new = person()
    assignment = assignment_create(
        actor=world.cure, person=new, office_type=office("catechiste"), node=world.saint_dominique
    )
    assignment_terminate(actor=world.cure, assignment=assignment)

    actions = list(
        AuditEvent.objects.filter(target_id=str(assignment.pk)).order_by("at").values_list("action", "actor_id")
    )
    assert actions == [("office.nomination", world.cure.pk), ("office.fin", world.cure.pk)]


def test_audit_is_insert_only(world):
    event = AuditEvent.objects.create(action="x", target_type="t", target_id="1")
    event.action = "y"
    with pytest.raises(ValueError):
        event.save()
    with pytest.raises(ValueError):
        event.delete()


def test_nobody_appoints_themselves(world):
    """Sinon un évêque se ferait vicaire pour obtenir messagerie.recevoir_fideles."""
    with pytest.raises(PermissionDeniedError) as exc:
        assignment_create(actor=world.eveque, person=world.eveque, office_type=office("vicaire_paroissial"), node=world.saint_dominique)
    assert exc.value.code == "self_appointment"


def test_frozen_catalogue_migration_matches_the_runtime_profile():
    """Les migrations de catalogue (0004, puis 0009 pour les dons) sont des copies figées : leur
    cumul doit rester égal au profil (sinon : écrire une nouvelle migration de catalogue)."""
    import importlib

    from apps.hierarchy.profiles import CAPABILITIES, OFFICES

    frozen = importlib.import_module("apps.hierarchy.migrations.0004_seed_offices_catalogue")
    dons = importlib.import_module("apps.hierarchy.migrations.0009_dons_capacites")
    capabilities = [c[0] for c in frozen.CAPABILITIES] + [c[0] for c in dons.CAPABILITIES]
    assert capabilities == [c["code"] for c in CAPABILITIES]
    office_caps = {o[0]: set(o[8]) for o in frozen.OFFICES}
    appointed = {o[0]: sorted(o[5]) for o in frozen.OFFICES}
    for code, extra in dons.OFFICE_CAPABILITIES.items():
        office_caps[code] |= set(extra)
    office_caps[dons.ECONOME["code"]] = set(dons.ECONOME["capabilities"])
    appointed[dons.ECONOME["code"]] = sorted(dons.ECONOME["appointed_by"])
    assert {k: sorted(v) for k, v in office_caps.items()} == {o["code"]: sorted(o["capabilities"]) for o in OFFICES}
    assert appointed == {o["code"]: sorted(o["appointed_by"]) for o in OFFICES}
