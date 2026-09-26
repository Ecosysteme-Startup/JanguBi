"""Vérification de l'état de vie, mouvement annuel, migration des anciens droits, API L2."""

from datetime import date

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.core.exceptions import ApplicationError, PermissionDeniedError
from apps.hierarchy import authz
from apps.hierarchy.enums import AssignmentStatus, StatutVerification
from apps.hierarchy.imports import assignments_import_csv
from apps.hierarchy.models import AuditEvent, OfficeAssignment
from apps.hierarchy.services_offices import person_declaration_submit, person_verification_decide
from apps.hierarchy.tests.factories import make_node, nominate, office, person, priest
from apps.users.tests.factories import SuperAdminFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(tree):
    tree.chancelier = person("chancelier@dakar.sn")
    tree.cure = priest("cure@sd.sn")
    nominate(tree.chancelier, "chancelier", tree.dakar)
    nominate(tree.cure, "cure", tree.saint_dominique)
    return tree


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# --- Déclaration et vérification (EF-PER-01, -02 ; RG-07) --------------------------------------


def test_declaration_stays_declared_and_grants_nothing(world):
    fidele = person(verified=False)
    person_declaration_submit(person=fidele, etat_de_vie="clerc", degre_ordre="pretre", incardination_node=world.dakar)

    fidele.refresh_from_db()
    assert fidele.statut_verification == StatutVerification.DECLARE
    assert authz.capacites(fidele) == []


def test_chancellor_verifies_a_priest_incardinated_in_his_diocese(world):
    candidate = person(verified=False)
    person_declaration_submit(person=candidate, etat_de_vie="clerc", degre_ordre="pretre", incardination_node=world.dakar)

    person_verification_decide(actor=world.chancelier, person=candidate, decision="verifie")

    candidate.refresh_from_db()
    assert candidate.statut_verification == StatutVerification.VERIFIE
    assert candidate.verified_by == world.chancelier
    assert AuditEvent.objects.filter(action="personne.verification", target_id=str(candidate.pk)).exists()


def test_peers_cannot_verify(world):
    """Un curé ne vérifie pas un diacre : seule la chancellerie (personnes.verifier)."""
    candidate = person(verified=False)
    person_declaration_submit(person=candidate, etat_de_vie="clerc", degre_ordre="diacre_permanent", incardination_node=world.dakar)
    with pytest.raises(PermissionDeniedError):
        person_verification_decide(actor=world.cure, person=candidate, decision="verifie")


def test_chancellor_of_dakar_cannot_verify_a_thies_priest(world):
    candidate = person(verified=False)
    person_declaration_submit(person=candidate, etat_de_vie="clerc", degre_ordre="pretre", incardination_node=world.thies)
    with pytest.raises(PermissionDeniedError):
        person_verification_decide(actor=world.chancelier, person=candidate, decision="verifie")


def test_no_self_verification(world):
    admin = SuperAdminFactory.create(etat_de_vie="clerc", degre_ordre="pretre")
    with pytest.raises(PermissionDeniedError):
        person_verification_decide(actor=admin, person=admin, decision="verifie")


def test_changing_a_verified_declaration_resets_it(world):
    verified = priest(incardination_node=world.dakar)
    person_declaration_submit(person=verified, etat_de_vie="clerc", degre_ordre="eveque", incardination_node=world.dakar)
    verified.refresh_from_db()
    assert verified.statut_verification == StatutVerification.DECLARE


def test_inconsistent_declaration_is_rejected(world):
    with pytest.raises(ApplicationError):
        person_declaration_submit(person=person(), etat_de_vie="laic", degre_ordre="pretre")
    with pytest.raises(ApplicationError):
        person_declaration_submit(person=person(), etat_de_vie="clerc", incardination_node=world.saint_dominique, degre_ordre="pretre")


# --- Mouvement annuel (EF-PER-07) --------------------------------------------------------


def test_annual_movement_simulation_then_atomic_application(world):
    new_cure = priest("nouveau@sd.sn")
    secretary = person("sec@st.sn")
    content = (
        "action,email,office,node_code\n"
        "nommer,nouveau@sd.sn,cure,T-SD\n"
        "nommer,sec@st.sn,secretaire_paroissial,T-ST\n"
    )

    dry = assignments_import_csv(actor=world.chancelier, content=content, effective_date=date(2026, 10, 1))
    assert [line.status for line in dry.lines] == ["warning", "error"]
    assert "titulaire précédent" in dry.lines[0].message
    assert "nommer" in dry.lines[1].message.lower()  # le chancelier n'est pas « nommeur » de secrétaires
    assert not OfficeAssignment.objects.filter(person=new_cure).exists()

    ok = assignments_import_csv(
        actor=world.chancelier, content=content.rsplit("\n", 2)[0] + "\n", effective_date=date(2026, 10, 1), dry_run=False
    )
    assert ok.applied
    old = OfficeAssignment.objects.get(person=world.cure)
    assert old.end_date == date(2026, 9, 30)
    new = OfficeAssignment.objects.get(person=new_cure)
    assert (new.start_date, new.node) == (date(2026, 10, 1), world.saint_dominique)
    assert not OfficeAssignment.objects.filter(person=secretary).exists()


def test_annual_movement_errors(world):
    content = (
        "action,email,office,node_code\n"
        "muter,x@y.sn,cure,T-SD\n"
        "nommer,inconnu@y.sn,cure,T-SD\n"
        "terminer,cure@sd.sn,vicaire_paroissial,T-SD\n"
    )
    report = assignments_import_csv(actor=world.chancelier, content=content, effective_date=date(2026, 10, 1), dry_run=False)

    assert report.errors == 3 and not report.applied
    assert "Action inconnue" in report.lines[0].message
    assert "Aucun compte" in report.lines[1].message
    assert "Aucune nomination" in report.lines[2].message


# --- API ---------------------------------------------------------------------------------


def test_me_capacites_api(world):
    response = client_for(world.cure).get("/api/v1/me/capacites/")

    assert response.status_code == 200
    assert {"capacite": "actes.traiter", "node_id": str(world.saint_dominique.pk), "node_name": "Saint-Dominique", "herite": True, "office": "cure", "node_type": "paroisse"} in response.data


def test_me_capacites_requires_authentication(db):
    assert APIClient().get("/api/v1/me/capacites/").status_code in (401, 403)


def test_assignment_api_create_list_terminate(world):
    client = client_for(world.cure)
    new = person("referent@sd.sn")

    created = client.post(
        "/api/v1/hierarchy/assignments/",
        {"person_id": str(new.pk), "office": "referent_numerique", "node_id": str(world.saint_dominique.pk)},
        format="json",
    )
    listing = client.get("/api/v1/hierarchy/assignments/", {"node": str(world.saint_dominique.pk)})
    ended = client.patch(f"/api/v1/hierarchy/assignments/{created.data['id']}/", {"action": "terminer"}, format="json")

    assert created.status_code == 201 and created.data["status"] == "active"
    assert {a["office"] for a in listing.data["results"]} == {"cure", "referent_numerique"}
    assert ended.data["status"] == AssignmentStatus.TERMINEE


def test_assignment_api_forbidden_is_403_in_v1_format(world):
    response = client_for(world.cure).post(
        "/api/v1/hierarchy/assignments/",
        {"person_id": str(priest().pk), "office": "vicaire_paroissial", "node_id": str(world.saint_dominique.pk)},
        format="json",
    )
    assert response.status_code == 403
    assert response.data["error"]["code"] == "appointment_forbidden"


def test_other_people_assignments_are_invisible(world):
    stranger = person()
    assignment = OfficeAssignment.objects.get(person=world.cure)
    response = client_for(stranger).get(f"/api/v1/hierarchy/assignments/{assignment.pk}/")
    assert response.status_code == 404


def test_assignment_import_api(world):
    priest("nouveau@sd.sn")
    file = SimpleUploadedFile("m.csv", b"action,email,office,node_code\nnommer,nouveau@sd.sn,cure,T-SD\n")
    response = client_for(world.chancelier).post(
        "/api/v1/hierarchy/assignments/import/?effective_date=2026-10-01", {"file": file}, format="multipart"
    )
    assert response.status_code == 200
    assert response.data["warnings"] == 1 and response.data["dry_run"]


def test_verification_api(world):
    candidate = person(verified=False)
    person_declaration_submit(person=candidate, etat_de_vie="clerc", degre_ordre="pretre", incardination_node=world.dakar)
    client = client_for(world.chancelier)

    queue = client.get("/api/v1/hierarchy/verifications/")
    decided = client.post(f"/api/v1/hierarchy/verifications/{candidate.pk}/decision/", {"decision": "verifie"}, format="json")

    assert [p["email"] for p in queue.data["results"]] == [candidate.email]
    assert decided.data["statut_verification"] == "verifie"
    assert client_for(world.cure).get("/api/v1/hierarchy/verifications/").status_code == 403


def test_out_of_scope_verification_is_a_404(world):
    candidate = person(verified=False)
    person_declaration_submit(person=candidate, etat_de_vie="clerc", degre_ordre="pretre", incardination_node=world.thies)

    response = client_for(world.chancelier).post(
        f"/api/v1/hierarchy/verifications/{candidate.pk}/decision/", {"decision": "verifie"}, format="json"
    )

    assert response.status_code == 404


def test_me_declaration_api(world):
    fidele = person(verified=False)
    response = client_for(fidele).post(
        "/api/v1/me/declaration/",
        {"etat_de_vie": "clerc", "degre_ordre": "diacre_permanent", "incardination_node_id": str(world.dakar.pk)},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["statut_verification"] == "declare"
    assert response.data["incardination_node"]["code"] == "T-DAK"


def test_audit_api_is_scoped_to_audit_voir(world):
    new = person()
    client_for(world.cure).post(
        "/api/v1/hierarchy/assignments/",
        {"person_id": str(new.pk), "office": "catechiste", "node_id": str(world.saint_dominique.pk)},
        format="json",
    )
    thies_cure = priest()
    nominate(thies_cure, "cure", world.thies_parish)

    own = client_for(world.cure).get("/api/v1/audit/")
    other = client_for(thies_cure).get("/api/v1/audit/")

    assert [e["action"] for e in own.data["results"]] == ["office.nomination"]
    assert other.data["count"] == 0
    assert client_for(person()).get("/api/v1/audit/").status_code == 403


def test_audit_api_node_filter_covers_the_subtree_and_exposes_actor_and_truncated_ip(world):
    """``audit.voir`` sur le diocèse : filtre ``node`` = ce nœud et son sous-arbre ; IP tronquée."""
    from apps.users.tests.factories import ProfileFactory

    ProfileFactory(user=world.cure, first_name="Jean", last_name="Sarr")
    ProfileFactory(user=world.chancelier, first_name="Awa", last_name="Diop")
    new = person()
    client_for(world.cure).post(
        "/api/v1/hierarchy/assignments/",
        {"person_id": str(new.pk), "office": "catechiste", "node_id": str(world.saint_dominique.pk)},
        format="json",
        REMOTE_ADDR="10.0.0.1",
        HTTP_X_FORWARDED_FOR="203.0.113.77",
    )
    thies_admin = person()
    nominate(thies_admin, "chancelier", world.thies)

    dakar = client_for(world.chancelier).get("/api/v1/audit/", {"node": str(world.dakar.pk)})
    parish = client_for(world.chancelier).get("/api/v1/audit/", {"node": str(world.saint_dominique.pk)})
    sibling = client_for(world.chancelier).get("/api/v1/audit/", {"node": str(world.sainte_therese.pk)})
    foreign = client_for(thies_admin).get("/api/v1/audit/", {"node": str(world.dakar.pk)})

    assert dakar.status_code == 200
    [event] = dakar.data["results"]
    assert event["action"] == "office.nomination"
    assert event["actor_name"] == "Jean Sarr"
    assert event["ip"] == "203.0.113.0"
    assert parish.data["count"] == 1
    assert sibling.data["count"] == 0
    assert foreign.data["count"] == 0


def test_audit_api_platform_sees_everything_and_system_events_have_no_actor(world):
    from apps.hierarchy.audit import audit_log

    audit_log(actor=None, action="office.expiration", target=world.thies_parish, node=world.thies_parish)
    audit_log(actor=world.cure, action="conformite.consentement", target=world.cure)

    response = client_for(SuperAdminFactory.create()).get("/api/v1/audit/")

    rows = {e["action"]: e for e in response.data["results"]}
    assert set(rows) == {"office.expiration", "conformite.consentement"}
    assert rows["office.expiration"]["actor_name"] is None
    assert rows["office.expiration"]["ip"] is None
    assert rows["conformite.consentement"]["actor_name"] == "cure@sd.sn"


def test_audit_api_requires_authentication(world):
    assert APIClient().get("/api/v1/audit/").status_code in (401, 403)


def test_capability_override_api_is_platform_only(world):
    payload = {"diocese_node_id": str(world.thies.pk), "office": "cure", "capability": "actes.traiter"}
    assert client_for(world.chancelier).post("/api/v1/hierarchy/capability-overrides/", payload, format="json").status_code == 403

    created = client_for(SuperAdminFactory.create()).post("/api/v1/hierarchy/capability-overrides/", payload, format="json")
    assert created.status_code == 201


# --- Écriture de la structure par capacité ------------------------------------------------------


def test_chancellor_creates_a_deanery_in_his_diocese_only(world):
    client = client_for(world.chancelier)
    ok = client.post("/api/v1/hierarchy/nodes/", {"type": "doyenne", "name": "Niayes", "parent_id": str(world.dakar.pk)}, format="json")
    ko = client.post("/api/v1/hierarchy/nodes/", {"type": "doyenne", "name": "X", "parent_id": str(world.thies.pk)}, format="json")

    assert ok.status_code == 201
    assert ko.status_code == 403


def test_cure_manages_schedules_but_not_structure(world):
    from apps.hierarchy.tests.factories import make_place

    place = make_place(world.saint_dominique, "Église", is_main=True)
    client = client_for(world.cure)

    schedule = client.put(
        f"/api/v1/hierarchy/places/{place.pk}/schedule/", {"items": [{"weekday": 6, "start_time": "09:30"}]}, format="json"
    )
    structure = client.patch(f"/api/v1/hierarchy/places/{place.pk}/", {"name": "Autre"}, format="json")
    ceb = client.post(
        "/api/v1/hierarchy/nodes/", {"type": "ceb", "name": "CEB", "parent_id": str(world.saint_dominique.pk)}, format="json"
    )

    assert schedule.status_code == 200
    assert structure.status_code == 403
    assert ceb.status_code == 403


def test_node_import_checks_each_row(world):
    make_node("paroisse", "Autre", world.thies, code="T-THI-2")
    file = SimpleUploadedFile(
        "n.csv", "code,type,name,parent_code\nD1,doyenne,Nouveau,T-DAK\nD2,doyenne,Ailleurs,T-THI\n".encode()
    )
    response = client_for(world.chancelier).post("/api/v1/hierarchy/import/nodes/", {"file": file}, format="multipart")

    assert [line["status"] for line in response.data["lines"]] == ["ok", "error"]
    assert "Vous ne pouvez pas" in response.data["lines"][1]["message"]


def test_office_types_api(world):
    response = client_for(person()).get("/api/v1/hierarchy/office-types/")
    cure = next(o for o in response.data if o["code"] == "cure")
    assert cure["appointed_by"] == ["chancelier", "eveque_diocesain"] or set(cure["appointed_by"]) == {
        "chancelier",
        "eveque_diocesain",
    }
    assert "actes.traiter" in cure["capabilities"]
    assert office("eveque_diocesain").appointed_by_platform
