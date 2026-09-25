from datetime import date, time

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.hierarchy.models import MassSchedule, Node, PlaceOfWorship
from apps.hierarchy.services import schedule_exception_create, schedule_replace
from apps.hierarchy.tests.factories import make_place
from apps.users.tests.factories import BaseUserFactory, SuperAdminFactory

pytestmark = pytest.mark.django_db

BASE = "/api/v1/hierarchy"


@pytest.fixture
def anon() -> APIClient:
    return APIClient()


@pytest.fixture
def admin() -> APIClient:
    client = APIClient()
    client.force_authenticate(user=SuperAdminFactory.create())
    return client


@pytest.fixture
def fidele() -> APIClient:
    client = APIClient()
    client.force_authenticate(user=BaseUserFactory.create())
    return client


# --- Lecture publique -------------------------------------------------------------


def test_node_types_are_public(anon, tree):
    response = anon.get(f"{BASE}/node-types/")

    assert response.status_code == 200
    paroisse = next(t for t in response.data if t["code"] == "paroisse")
    assert set(paroisse["allowed_parent_types"]) == {"doyenne", "zone", "diocese"}
    assert paroisse["holds_registers"] is True


def test_node_list_is_public_paginated_and_filterable(anon, tree):
    response = anon.get(f"{BASE}/nodes/", {"type": "paroisse", "within": str(tree.dakar.pk)})

    assert response.status_code == 200
    assert response.data["count"] == 2
    first = response.data["results"][0]
    assert first["type"] == {"code": "paroisse", "label": "Paroisse"}
    assert first["parent_id"] == str(tree.doyenne.pk)
    assert "legacy_id" not in first


def test_node_list_does_not_query_parents_one_by_one(anon, tree, django_assert_max_num_queries):
    # 7 nœuds listés : un N+1 sur les parents dépasserait largement ce plafond
    # (transaction ATOMIC_REQUESTS + comptage + page + parents en une requête).
    with django_assert_max_num_queries(6):
        response = anon.get(f"{BASE}/nodes/")
    assert response.data["count"] == 7


def test_node_detail_children_and_ancestors(anon, tree):
    detail = anon.get(f"{BASE}/nodes/{tree.saint_dominique.pk}/")
    children = anon.get(f"{BASE}/nodes/{tree.doyenne.pk}/children/")
    ancestors = anon.get(f"{BASE}/nodes/{tree.saint_dominique.pk}/ancestors/")

    assert detail.data["code"] == "T-SD"
    assert {c["code"] for c in children.data} == {"T-SD", "T-ST"}
    assert [a["code"] for a in ancestors.data] == ["T-DAKP", "T-DAK", "T-PM"]
    assert ancestors.data[0]["parent_id"] is None


def test_unknown_node_returns_v1_error(anon, db):
    response = anon.get(f"{BASE}/nodes/00000000-0000-0000-0000-000000000000/")

    assert response.status_code == 404
    assert response.data["error"]["code"] == "not_found"


# --- Écriture ---------------------------------------------------------------------


def test_anonymous_cannot_create(anon, tree):
    response = anon.post(f"{BASE}/nodes/", {"type": "ceb", "name": "CEB", "parent_id": str(tree.saint_dominique.pk)})
    assert response.status_code in (401, 403)
    assert "error" in response.data


def test_fidele_cannot_create(fidele, tree):
    response = fidele.post(
        f"{BASE}/nodes/", {"type": "ceb", "name": "CEB", "parent_id": str(tree.saint_dominique.pk)}, format="json"
    )
    assert response.status_code == 403
    assert response.data["error"]["code"] == "permission_denied"


def test_admin_creates_a_node(admin, tree):
    response = admin.post(
        f"{BASE}/nodes/",
        {"type": "ceb", "name": "CEB Saint-Paul", "parent_id": str(tree.saint_dominique.pk), "city": "Dakar"},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["parent_id"] == str(tree.saint_dominique.pk)
    assert Node.objects.filter(name="CEB Saint-Paul").exists()


def test_forbidden_parent_returns_400_with_explicit_message(admin, tree):
    response = admin.post(
        f"{BASE}/nodes/", {"type": "diocese", "name": "Diocèse", "parent_id": str(tree.doyenne.pk)}, format="json"
    )

    assert response.status_code == 400
    assert response.data["error"]["code"] == "parent_type_not_allowed"
    assert "Doyenné" in response.data["error"]["message"]


def test_invalid_payload_returns_validation_error(admin, tree):
    response = admin.post(f"{BASE}/nodes/", {"type": "ceb"}, format="json")

    assert response.status_code == 400
    assert response.data["error"]["code"] == "validation_error"
    assert "name" in response.data["error"]["details"]


def test_admin_patches_status(admin, tree):
    response = admin.patch(f"{BASE}/nodes/{tree.sainte_therese.pk}/", {"status": "supprime"}, format="json")

    assert response.status_code == 200
    assert response.data["status"] == "supprime"


# --- Lieux et horaires ----------------------------------------------------------


def test_places_crud_and_single_main(admin, anon, tree):
    url = f"{BASE}/nodes/{tree.saint_dominique.pk}/places/"
    first = admin.post(url, {"name": "Église", "kind": "eglise_paroissiale", "is_main": True}, format="json")
    second = admin.post(url, {"name": "Autre", "is_main": True}, format="json")
    listing = anon.get(url)

    assert first.status_code == 201
    assert second.status_code == 400 and second.data["error"]["code"] == "main_place_exists"
    assert [p["name"] for p in listing.data] == ["Église"]

    patch = admin.patch(f"{BASE}/places/{first.data['id']}/", {"name": "Église Saint-Dominique"}, format="json")
    assert patch.data["name"] == "Église Saint-Dominique"


def test_schedule_put_and_get(admin, anon, tree):
    place = make_place(tree.saint_dominique, "Église", is_main=True)
    url = f"{BASE}/places/{place.pk}/schedule/"

    put = admin.put(
        url,
        {"items": [{"weekday": 6, "start_time": "09:30"}, {"weekday": 5, "start_time": "16:00", "kind": "confession"}]},
        format="json",
    )
    get = anon.get(url)

    assert put.status_code == 200
    assert [(s["weekday"], s["start_time"]) for s in get.data] == [(5, "16:00:00"), (6, "09:30:00")]


def test_schedule_put_rejects_end_before_start(admin, tree):
    place = make_place(tree.saint_dominique, "Église", is_main=True)
    response = admin.put(
        f"{BASE}/places/{place.pk}/schedule/",
        {"items": [{"weekday": 0, "start_time": "08:00", "end_time": "07:00"}]},
        format="json",
    )
    assert response.status_code == 400
    assert MassSchedule.objects.count() == 0


def test_exceptions_create_list_delete(admin, anon, tree):
    place = make_place(tree.saint_dominique, "Église", is_main=True)
    url = f"{BASE}/places/{place.pk}/exceptions/"

    created = admin.post(url, {"date": "2099-12-24", "kind": "messe", "start_time": "23:00", "note": "Veillée"}, format="json")
    listing = anon.get(url)
    deleted = admin.delete(f"{url}{created.data['id']}/")

    assert created.status_code == 201
    assert [e["note"] for e in listing.data] == ["Veillée"]
    assert deleted.status_code == 204


def test_public_week(anon, tree):
    place = make_place(tree.saint_dominique, "Église", is_main=True)
    schedule_replace(place=place, items=[{"weekday": 6, "start_time": time(9, 30)}, {"weekday": 6, "start_time": time(11, 30)}])
    schedule_exception_create(place=place, date=date(2026, 10, 4), cancelled=True, start_time=time(11, 30))

    response = anon.get(f"/api/v1/public/nodes/{tree.saint_dominique.pk}/week/", {"start": "2026-09-28"})

    assert response.status_code == 200
    assert response.data["end"] == "2026-10-04"
    assert [(o["date"], o["start_time"], o["place_name"]) for o in response.data["occurrences"]] == [
        ("2026-10-04", "09:30:00", "Église")
    ]


def test_public_directory(anon, tree):
    response = anon.get("/api/v1/public/nodes/", {"diocese": str(tree.dakar.pk), "q": "domi"})

    assert response.status_code == 200
    assert [n["code"] for n in response.data["results"]] == ["T-SD"]


# --- Import -----------------------------------------------------------------------


def _csv(content: str) -> SimpleUploadedFile:
    return SimpleUploadedFile("import.csv", content.encode("utf-8"), content_type="text/csv")


def test_import_dry_run_then_apply(admin, tree):
    content = "code,type,name,parent_code\nT-CEB,ceb,CEB Test,T-SD\n"

    dry = admin.post(f"{BASE}/import/nodes/", {"file": _csv(content)}, format="multipart")
    assert dry.status_code == 200 and dry.data["dry_run"] and not dry.data["applied"]
    assert not Node.objects.filter(code="T-CEB").exists()

    applied = admin.post(f"{BASE}/import/nodes/?dry_run=false", {"file": _csv(content)}, format="multipart")
    assert applied.data["applied"]
    assert Node.objects.filter(code="T-CEB").exists()


def test_import_places(admin, tree):
    content = "node_code,name,kind,is_main\nT-SD,Église,eglise_paroissiale,1\n"
    response = admin.post(f"{BASE}/import/places/?dry_run=false", {"file": _csv(content)}, format="multipart")
    assert response.data["applied"]
    assert PlaceOfWorship.objects.filter(node=tree.saint_dominique, is_main=True).exists()


def test_import_is_forbidden_to_fidele(fidele, tree):
    response = fidele.post(f"{BASE}/import/nodes/", {"file": _csv("code,type,name,parent_code\n")}, format="multipart")
    assert response.status_code == 403
