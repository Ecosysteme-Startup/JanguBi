"""Agenda : période et pagination côté staff, inscription enrichie (nombre de personnes,
remarque, clôture), colonnes des inscrits (écarts F9, lot g4)."""

import datetime

import pytest
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.test import APIClient

from apps.agenda.services import event_create, event_register, event_update
from apps.core.exceptions import ApplicationError, ConflictError
from apps.hierarchy.tests.factories import nominate, person

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(tree):
    tree.catechiste = person("catechiste@sd.sn")
    nominate(tree.catechiste, "catechiste", tree.saint_dominique)
    return tree


def aware(*args) -> datetime.datetime:
    return timezone.make_aware(datetime.datetime(*args))


def event(world, start=None, **kwargs):
    start = start or timezone.now() + datetime.timedelta(days=3)
    fields = {
        "organizer": world.catechiste,
        "title": "Récollection des CEB",
        "start_at": start,
        "end_at": start + datetime.timedelta(hours=3),
        "node": world.saint_dominique,
    }
    return event_create(**{**fields, **kwargs})


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# --- Période et pagination (staff) ---------------------------------------------------------------


@freeze_time("2026-09-24 10:00:00")
def test_staff_list_filters_by_period_including_past(world):
    past = event(world, start=aware(2026, 9, 2, 9), title="Passé")
    october = event(world, start=aware(2026, 10, 10, 8, 30), title="Octobre")
    event(world, start=aware(2026, 11, 1, 10), title="Novembre")
    client = client_for(world.catechiste)

    september = client.get("/api/v1/staff/agenda/", {"from": "2026-09-01", "to": "2026-09-30"})
    only_october = client.get("/api/v1/staff/agenda/", {"from": "2026-10-01", "to": "2026-10-31"})
    last_day_included = client.get("/api/v1/staff/agenda/", {"from": "2026-10-10", "to": "2026-10-10"})
    default = client.get("/api/v1/staff/agenda/")

    assert [e["id"] for e in september.data["results"]] == [past.pk]
    assert [e["id"] for e in only_october.data["results"]] == [october.pk]
    assert [e["id"] for e in last_day_included.data["results"]] == [october.pk]
    assert past.pk not in [e["id"] for e in default.data["results"]]


def test_staff_period_must_be_ordered(world):
    response = client_for(world.catechiste).get("/api/v1/staff/agenda/", {"from": "2026-10-31", "to": "2026-10-01"})
    assert response.status_code == 400


def test_staff_list_paginates_beyond_fifty(world):
    start = timezone.now() + datetime.timedelta(days=2)
    for i in range(55):
        event(world, start=start + datetime.timedelta(hours=i), title=f"Messe {i}")
    client = client_for(world.catechiste)

    first = client.get("/api/v1/staff/agenda/", {"limit": 50})
    rest = client.get("/api/v1/staff/agenda/", {"limit": 50, "offset": 50})

    assert first.data["count"] == 55 and len(first.data["results"]) == 50
    assert len(rest.data["results"]) == 5
    assert {e["id"] for e in first.data["results"]}.isdisjoint({e["id"] for e in rest.data["results"]})


# --- Inscription enrichie ------------------------------------------------------------------------


def test_register_with_seats_and_note_over_http(world):
    e = event(world, max_participants=5)
    fidele = person("awa@sd.sn")

    response = client_for(fidele).post(
        f"/api/v1/agenda/{e.pk}/register/", {"seats": 2, "note": "  Une place à l'avant du car.  "}, format="json"
    )

    assert response.status_code == 201
    assert response.data["my_seats"] == 2 and response.data["my_note"] == "Une place à l'avant du car."
    assert response.data["seats_taken"] == 2 and response.data["seats_remaining"] == 3
    assert response.data["registrations_count"] == 1 and response.data["registrations_open"] is True


def test_capacity_counts_seats_not_registrations(world):
    e = event(world, max_participants=3)
    event_register(event=e, user=person(), seats=2)

    with pytest.raises(ConflictError) as too_many:
        event_register(event=e, user=person(), seats=2)
    event_register(event=e, user=person(), seats=1)
    with pytest.raises(ConflictError) as full:
        event_register(event=e, user=person())

    assert too_many.value.code == "not_enough_seats"
    assert full.value.code == "event_full"


def test_registering_again_updates_seats_and_note(world):
    e = event(world, max_participants=3)
    fidele = person()
    event_register(event=e, user=fidele, seats=1, note="")
    event_register(event=e, user=person(), seats=1)

    updated = event_register(event=e, user=fidele, seats=2, note="Avec ma tante")

    assert (updated.seats, updated.note) == (2, "Avec ma tante")
    assert e.registrations.count() == 2
    with pytest.raises(ConflictError):
        event_register(event=e, user=fidele, seats=3)


@pytest.mark.parametrize("payload", [{"seats": 0}, {"seats": 11}, {"note": "x" * 301}])
def test_register_input_is_bounded(world, payload):
    response = client_for(person()).post(f"/api/v1/agenda/{event(world).pk}/register/", payload, format="json")
    assert response.status_code == 400


def test_register_requires_authentication(world):
    assert APIClient().post(f"/api/v1/agenda/{event(world).pk}/register/", {}, format="json").status_code == 401


def test_registrations_close_at_the_closing_date(world):
    start = aware(2026, 10, 10, 8, 30)
    with freeze_time("2026-09-24 10:00:00"):
        e = event(world, start=start, registration_closes_at=aware(2026, 10, 8, 18))
        event_register(event=e, user=person())

    with freeze_time("2026-10-08 18:00:01"), pytest.raises(ApplicationError) as closed:
        event_register(event=e, user=person())
    with freeze_time("2026-10-08 18:00:01"):
        detail = APIClient().get(f"/api/v1/agenda/{e.pk}/")

    assert closed.value.code == "registrations_closed"
    assert detail.data["registrations_open"] is False
    assert detail.data["registration_closes_at"].startswith("2026-10-08T18:00")


def test_closing_date_cannot_follow_the_end(world):
    start = timezone.now() + datetime.timedelta(days=3)
    with pytest.raises(ApplicationError) as exc:
        event(world, start=start, registration_closes_at=start + datetime.timedelta(days=1))
    e = event(world, start=start)
    with pytest.raises(ApplicationError):
        event_update(
            event=e, actor=world.catechiste, data={"registration_closes_at": start + datetime.timedelta(days=1)}
        )

    assert exc.value.code == "invalid_registration_closing"


def test_capacity_cannot_drop_below_reserved_seats(world):
    e = event(world, max_participants=5)
    event_register(event=e, user=person(), seats=3)
    with pytest.raises(ApplicationError) as exc:
        event_update(event=e, actor=world.catechiste, data={"max_participants": 2})
    assert exc.value.code == "capacity_below_registrations"


# --- Côté staff : inscrits et CSV ----------------------------------------------------------------


def test_staff_sees_seats_and_note_in_list_and_csv(world):
    from apps.users.models import Profile

    e = event(world, max_participants=10)
    awa = person("awa@sd.sn")
    Profile.objects.create(user=awa, first_name="Awa", last_name="Ndiaye")
    event_register(event=e, user=awa, seats=2, note="Besoin du car")
    event_register(event=e, user=person("malin@sd.sn"), seats=1, note="=HYPERLINK(1)")
    client = client_for(world.catechiste)

    listing = client.get(f"/api/v1/staff/agenda/{e.pk}/registrations/")
    csv = client.get(f"/api/v1/staff/agenda/{e.pk}/registrations.csv").content.decode("utf-8-sig")
    staff_detail = client.get(f"/api/v1/staff/agenda/{e.pk}/")

    first = listing.data["results"][0]
    assert (first["seats"], first["note"]) == (2, "Besoin du car")
    assert csv.splitlines()[0] == "Nom;E-mail;Personnes;Remarque;Inscrit le"
    assert "Awa Ndiaye;awa@sd.sn;2;Besoin du car;" in csv
    assert "'=HYPERLINK(1)" in csv  # pas d'injection de formule dans le tableur
    assert staff_detail.data["seats_taken"] == 3


def test_staff_sets_closing_date_over_http(world):
    start = timezone.now() + datetime.timedelta(days=5)
    closes = start - datetime.timedelta(days=2)
    client = client_for(world.catechiste)
    created = client.post(
        "/api/v1/staff/agenda/",
        {
            "node_id": str(world.saint_dominique.pk),
            "title": "Pèlerinage",
            "start_at": start.isoformat(),
            "end_at": (start + datetime.timedelta(hours=8)).isoformat(),
            "registration_closes_at": closes.isoformat(),
        },
        format="json",
    )
    cleared = client.patch(
        f"/api/v1/staff/agenda/{created.data['id']}/", {"registration_closes_at": None}, format="json"
    )

    assert created.status_code == 201 and created.data["registration_closes_at"] is not None
    assert cleared.status_code == 200 and cleared.data["registration_closes_at"] is None
