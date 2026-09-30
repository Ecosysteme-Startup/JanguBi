"""Qualité d'une nomination : le titre réel du titulaire (« Curé » ou « Administrateur
paroissial »), jamais la double forme du catalogue."""

import datetime

import pytest
from rest_framework.test import APIClient

from apps.core.exceptions import ApplicationError, PermissionDeniedError
from apps.hierarchy import authz
from apps.hierarchy.catalogue import load_offices_catalogue
from apps.hierarchy.imports import assignments_import_csv
from apps.hierarchy.models import AuditEvent, Capability, NodeType, OfficeAssignment, OfficeType
from apps.hierarchy.services_offices import assignment_create, assignment_quality_set
from apps.hierarchy.tests.factories import nominate, office, person, priest

pytestmark = pytest.mark.django_db

ASSIGNMENTS = "/api/v1/hierarchy/assignments/"


@pytest.fixture
def world(tree):
    tree.chancelier = person("chancelier@dakar.sn")
    nominate(tree.chancelier, "chancelier", tree.dakar)
    return tree


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# --- Catalogue --------------------------------------------------------------------------------


def test_cure_office_has_two_qualities_curé_first(db):
    assert office("cure").qualities == [
        {"code": "cure", "label": "Curé"},
        {"code": "administrateur", "label": "Administrateur paroissial"},
    ]
    assert office("vicaire_paroissial").qualities == []


def test_catalogue_completes_qualities_of_an_existing_office_without_overwriting(db):
    cure = office("cure")
    cure.qualities = []
    cure.save(update_fields=["qualities"])
    load_offices_catalogue(Capability=Capability, OfficeType=OfficeType, NodeType=NodeType)
    assert OfficeType.objects.get(code="cure").quality_codes == ["cure", "administrateur"]

    custom = [{"code": "cure", "label": "Curé-archiprêtre"}]
    OfficeType.objects.filter(code="cure").update(qualities=custom)
    load_offices_catalogue(Capability=Capability, OfficeType=OfficeType, NodeType=NodeType)
    assert OfficeType.objects.get(code="cure").qualities == custom


# --- Titre ----------------------------------------------------------------------------------


def test_title_is_the_quality_label_or_the_office_label(world):
    admin = nominate(priest(), "cure", world.saint_dominique, quality="administrateur")
    vicaire = nominate(priest(), "vicaire_paroissial", world.saint_dominique)
    legacy = OfficeAssignment(office_type=office("cure"), quality="")

    assert admin.title == "Administrateur paroissial"
    assert vicaire.title == "Vicaire paroissial"
    assert legacy.title == "Curé"  # qualité par défaut, jamais « Curé / administrateur paroissial »


# --- Service --------------------------------------------------------------------------------


def test_create_defaults_to_the_first_quality(world):
    assignment = assignment_create(
        actor=world.chancelier, person=priest(), office_type=office("cure"), node=world.saint_dominique
    )
    assert assignment.quality == "cure"


def test_create_accepts_administrateur_and_audits_it(world):
    assignment = assignment_create(
        actor=world.chancelier,
        person=priest(),
        office_type=office("cure"),
        node=world.saint_dominique,
        quality="administrateur",
    )
    assert assignment.title == "Administrateur paroissial"
    event = AuditEvent.objects.get(action="office.nomination", target_id=str(assignment.pk))
    assert event.metadata["quality"] == "administrateur"


def test_create_rejects_an_unknown_quality(world):
    with pytest.raises(ApplicationError) as exc:
        assignment_create(
            actor=world.chancelier, person=priest(), office_type=office("cure"), node=world.saint_dominique, quality="eveque"
        )
    assert exc.value.code == "invalid_quality"


def test_create_rejects_a_quality_on_an_office_without_qualities(world):
    with pytest.raises(ApplicationError) as exc:
        assignment_create(
            actor=world.chancelier,
            person=priest(),
            office_type=office("vicaire_paroissial"),
            node=world.saint_dominique,
            quality="cure",
        )
    assert exc.value.code == "invalid_quality"


def test_quality_set_turns_the_administrator_into_the_parish_priest(world):
    assignment = nominate(priest(), "cure", world.saint_dominique, quality="administrateur")

    assignment_quality_set(actor=world.chancelier, assignment=assignment, quality="cure")

    assignment.refresh_from_db()
    assert assignment.title == "Curé"
    assert AuditEvent.objects.filter(action="office.qualite", target_id=str(assignment.pk)).exists()


def test_quality_set_requires_the_appointing_authority(world):
    assignment = nominate(priest(), "cure", world.saint_dominique, quality="administrateur")
    with pytest.raises(PermissionDeniedError):
        assignment_quality_set(actor=person(), assignment=assignment, quality="cure")


def test_quality_set_refuses_a_closed_assignment(world):
    assignment = nominate(priest(), "cure", world.saint_dominique, status="terminee", end_date=datetime.date(2021, 1, 1))
    with pytest.raises(ApplicationError) as exc:
        assignment_quality_set(actor=world.chancelier, assignment=assignment, quality="cure")
    assert exc.value.code == "assignment_closed"


# --- Import CSV -------------------------------------------------------------------------------


def test_import_accepts_the_quality_column(world):
    priest("admin@sd.sn")
    content = "action,email,office,node_code,quality\nnommer,admin@sd.sn,cure,T-SD,administrateur\n"

    report = assignments_import_csv(
        actor=world.chancelier, content=content, effective_date=datetime.date(2026, 10, 1), dry_run=False
    )

    assert report.errors == 0
    assert OfficeAssignment.objects.get(person__email="admin@sd.sn").quality == "administrateur"


def test_import_reports_an_invalid_quality(world):
    priest("admin@sd.sn")
    content = "action,email,office,node_code,quality\nnommer,admin@sd.sn,cure,T-SD,pape\n"

    report = assignments_import_csv(
        actor=world.chancelier, content=content, effective_date=datetime.date(2026, 10, 1), dry_run=False
    )

    assert report.errors == 1


# --- API ------------------------------------------------------------------------------------


def test_office_types_expose_qualities(world):
    response = client_for(world.chancelier).get("/api/v1/hierarchy/office-types/")
    by_code = {o["code"]: o for o in response.data}
    assert by_code["cure"]["qualities"][1] == {"code": "administrateur", "label": "Administrateur paroissial"}
    assert by_code["doyen"]["qualities"] == []


def test_api_create_with_quality_returns_the_title(world):
    response = client_for(world.chancelier).post(
        ASSIGNMENTS,
        {
            "person_id": str(priest().pk),
            "office": "cure",
            "node_id": str(world.saint_dominique.pk),
            "quality": "administrateur",
        },
        format="json",
    )
    assert response.status_code == 201
    assert response.data["quality"] == "administrateur"
    assert response.data["office_label"] == "Administrateur paroissial"


def test_api_create_with_invalid_quality_is_400(world):
    response = client_for(world.chancelier).post(
        ASSIGNMENTS,
        {"person_id": str(priest().pk), "office": "cure", "node_id": str(world.saint_dominique.pk), "quality": "pape"},
        format="json",
    )
    assert response.status_code == 400
    assert response.data["error"]["code"] == "invalid_quality"


def test_api_patch_qualifier(world):
    assignment = nominate(priest(), "cure", world.saint_dominique, quality="administrateur")
    response = client_for(world.chancelier).patch(
        f"{ASSIGNMENTS}{assignment.pk}/", {"action": "qualifier", "quality": "cure"}, format="json"
    )
    assert response.status_code == 200
    assert response.data["office_label"] == "Curé"


def test_api_patch_qualifier_is_forbidden_to_a_stranger_with_the_team_view(world):
    """Le secrétaire voit l'équipe (tableau_bord.voir) mais ne nomme pas le curé."""
    secretaire = person()
    nominate(secretaire, "secretaire_paroissial", world.saint_dominique)
    assignment = nominate(priest(), "cure", world.saint_dominique, quality="administrateur")
    response = client_for(secretaire).patch(
        f"{ASSIGNMENTS}{assignment.pk}/", {"action": "qualifier", "quality": "cure"}, format="json"
    )
    assert response.status_code == 403


def test_me_capacites_exposes_the_title_of_the_granting_assignment(world):
    admin = priest()
    nominate(admin, "cure", world.saint_dominique, quality="administrateur")

    rows = client_for(admin).get("/api/v1/me/capacites/").data

    assert rows and {r["office_label"] for r in rows} == {"Administrateur paroissial"}
    assert {r["office"] for r in rows} == {"cure"}


def test_capacites_title_follows_a_quality_change(world):
    assignment = nominate(priest(), "cure", world.saint_dominique, quality="administrateur")
    authz.capacites(assignment.person)  # met les droits en cache
    assignment_quality_set(actor=world.chancelier, assignment=assignment, quality="cure")
    assert {r["office_label"] for r in authz.capacites(assignment.person)} == {"Curé"}


# --- Migration 0008 (aller-retour) ----------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_migration_0008_roundtrip_gives_existing_cure_assignments_the_cure_quality(tree):
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    before, after = [("hierarchy", "0007_node_secretariat")], [("hierarchy", "0008_office_qualities")]
    cure = priest()
    nominate(cure, "cure", tree.saint_dominique)
    OfficeType.objects.filter(code="cure").update(qualities=[])

    executor = MigrationExecutor(connection)
    # Revenir à 0007 défait aussi toutes les migrations qui en dépendent (hierarchy 0009+,
    # users 0004…) : sans restauration du schéma complet, les tests suivants tournent sur une
    # base amputée (ex. colonne users_baseuser.admin_node_id absente).
    try:
        executor.migrate(before)
        executor.loader.build_graph()
        executor.migrate(after)

        assert OfficeType.objects.get(code="cure").quality_codes == ["cure", "administrateur"]
        assert OfficeAssignment.objects.get(person=cure).quality == "cure"
        assert OfficeType.objects.get(code="vicaire_paroissial").qualities == []
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
