"""Agenda V1 : capacités, jauge (409), CSV, rappels (EF-PAROI-07, -08)."""

import datetime

import pytest
from django.core import mail
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.test import APIClient

from apps.agenda.models import EventRegistration
from apps.agenda.services import event_cancel, event_create, event_register, event_reminders_send, event_update
from apps.core.exceptions import ApplicationError, ConflictError, PermissionDeniedError
from apps.hierarchy.tests.factories import nominate, person, priest
from apps.messaging.models import Notification

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(tree):
    tree.catechiste = person("catechiste@sd.sn")
    tree.cure_thies = priest("cure@thies.sn")
    nominate(tree.catechiste, "catechiste", tree.saint_dominique)
    nominate(tree.cure_thies, "cure", tree.thies_parish)
    return tree


def event(world, **kwargs):
    start = timezone.now() + datetime.timedelta(days=3)
    fields = {
        "organizer": world.catechiste,
        "title": "Retraite des jeunes",
        "start_at": start,
        "end_at": start + datetime.timedelta(hours=3),
        "node": world.saint_dominique,
    }
    return event_create(**{**fields, **kwargs})


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_catechist_manages_events_of_her_parish_only(world):
    assert event(world).scope_node == world.saint_dominique
    with pytest.raises(PermissionDeniedError):
        event(world, node=world.sainte_therese)


def test_end_must_follow_start(world):
    now = timezone.now()
    with pytest.raises(ApplicationError):
        event(world, start_at=now + datetime.timedelta(days=1), end_at=now)


def test_full_event_returns_conflict(world):
    e = event(world, max_participants=1)
    first = person()
    event_register(event=e, user=first)
    assert event_register(event=e, user=first).user == first  # idempotent
    with pytest.raises(ConflictError):
        event_register(event=e, user=person())


def test_cancelled_event_refuses_registrations_and_notifies(world, django_capture_on_commit_callbacks):
    e = event(world)
    event_register(event=e, user=person("inscrit@sd.sn"))
    with django_capture_on_commit_callbacks(execute=True):
        event_cancel(event=e, actor=world.catechiste)
    assert [m.to for m in mail.outbox] == [["inscrit@sd.sn"]]
    with pytest.raises(ApplicationError):
        event_register(event=e, user=person())


def test_capacity_cannot_drop_below_registrations(world):
    e = event(world, max_participants=5)
    event_register(event=e, user=person())
    event_register(event=e, user=person())
    with pytest.raises(ApplicationError):
        event_update(event=e, actor=world.catechiste, data={"max_participants": 1})


def test_reminder_the_day_before_once_and_respecting_quiet_hours(world, django_capture_on_commit_callbacks):
    start = timezone.make_aware(datetime.datetime(2026, 10, 3, 9, 0))
    with freeze_time("2026-09-28 10:00:00"):
        e = event(world, start_at=start, end_at=start + datetime.timedelta(hours=2))
        registrant = person("inscrit@sd.sn")
        event_register(event=e, user=registrant)

    # La veille à 23 h : notification in-app tout de suite, e-mail différé à 6 h.
    with freeze_time("2026-10-02 23:00:00"), django_capture_on_commit_callbacks(execute=False) as callbacks:
        assert event_reminders_send() == 1
        assert event_reminders_send() == 0
    assert Notification.objects.filter(user=registrant, event_type="agenda.reminder").count() == 1
    assert len(callbacks) >= 1  # l'e-mail est planifié (eta), pas envoyé pendant le silence


def test_quiet_hours_are_computed_across_midnight():
    from apps.messaging.quiet_hours import quiet_until

    tz = timezone.get_current_timezone()
    at = lambda h, d=2: datetime.datetime(2026, 10, d, h, 30, tzinfo=tz)  # noqa: E731
    start, end = datetime.time(22), datetime.time(6)
    assert quiet_until(now=at(23), start=start, end=end) == datetime.datetime(2026, 10, 3, 6, 0, tzinfo=tz)
    assert quiet_until(now=at(2), start=start, end=end) == datetime.datetime(2026, 10, 2, 6, 0, tzinfo=tz)
    assert quiet_until(now=at(12), start=start, end=end) is None
    assert quiet_until(now=at(12), start=datetime.time(12), end=datetime.time(14)) is not None
    assert quiet_until(now=at(12), start=start, end=start) is None


# --- API --------------------------------------------------------------------------------------


def test_public_list_and_register_over_http(world):
    e = event(world, max_participants=1)
    listing = APIClient().get("/api/v1/agenda/", {"node": str(world.dakar.pk)})
    first = client_for(person()).post(f"/api/v1/agenda/{e.pk}/register/")
    full = client_for(person()).post(f"/api/v1/agenda/{e.pk}/register/")

    assert [x["id"] for x in listing.data["results"]] == [e.pk]
    assert first.status_code == 201 and first.data["is_registered"] and first.data["is_full"]
    assert full.status_code == 409 and full.data["error"]["code"] == "event_full"


def test_staff_create_and_csv_export(world):
    client = client_for(world.catechiste)
    start = timezone.now() + datetime.timedelta(days=5)
    created = client.post(
        "/api/v1/staff/agenda/",
        {
            "node_id": str(world.saint_dominique.pk),
            "title": "Veillée",
            "start_at": start.isoformat(),
            "end_at": (start + datetime.timedelta(hours=2)).isoformat(),
        },
        format="json",
    )
    from apps.users.models import Profile

    registrant = person("awa@sd.sn")
    Profile.objects.create(user=registrant, first_name="Awa", last_name="Ndiaye")
    client_for(registrant).post(f"/api/v1/agenda/{created.data['id']}/register/")

    csv = client.get(f"/api/v1/staff/agenda/{created.data['id']}/registrations.csv")

    assert created.status_code == 201
    assert csv.status_code == 200 and csv["Content-Type"].startswith("text/csv")
    content = csv.content.decode("utf-8-sig")
    assert "Awa Ndiaye;awa@sd.sn;" in content


def test_staff_of_another_parish_gets_404(world):
    e = event(world)
    assert client_for(world.cure_thies).get(f"/api/v1/staff/agenda/{e.pk}/").status_code == 404
    assert client_for(person()).get("/api/v1/staff/agenda/").status_code == 403


def test_unregister(world):
    e = event(world)
    fidele = person()
    client = client_for(fidele)
    client.post(f"/api/v1/agenda/{e.pk}/register/")
    assert client.delete(f"/api/v1/agenda/{e.pk}/register/").status_code == 204
    assert not EventRegistration.objects.filter(event=e, user=fidele).exists()


def test_one_failing_reminder_does_not_cancel_the_others(world, monkeypatch):
    from apps.agenda import services

    start = timezone.now() + datetime.timedelta(hours=12)
    failing = event(world, title="A", start_at=start, end_at=start + datetime.timedelta(hours=1))
    ok = event(world, title="B", start_at=start, end_at=start + datetime.timedelta(hours=1))
    real = services._event_remind

    def flaky(*, event, now):
        if event.pk == failing.pk:
            raise RuntimeError("panne simulée")
        real(event=event, now=now)

    monkeypatch.setattr(services, "_event_remind", flaky)
    assert event_reminders_send() == 1
    failing.refresh_from_db()
    ok.refresh_from_db()
    assert failing.reminder_sent_at is None and ok.reminder_sent_at is not None
