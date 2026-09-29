"""Rendez-vous de confession (SRS §3.7 EF-PRE-10 à 13 ; RG-08)."""

import datetime

import pytest
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.test import APIClient

from apps.confessions import services
from apps.confessions.models import ConfessionBooking, ConfessionSlot, ConfessionSlotRule
from apps.confessions.serializers import initials
from apps.core.exceptions import ApplicationError, ConflictError, PermissionDeniedError
from apps.hierarchy.tests.factories import make_place, nominate, person, priest
from apps.messaging.models import Notification
from apps.users.models import Profile

pytestmark = pytest.mark.django_db
B = ConfessionBooking.Status
NOW = "2026-10-05 08:00:00"  # lundi, Africa/Dakar = UTC


def named(user, first: str, last: str):
    Profile.objects.update_or_create(user=user, defaults={"first_name": first, "last_name": last})
    user.refresh_from_db()
    return user


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def world(tree):
    tree.place = make_place(tree.saint_dominique, "Église Saint-Dominique")
    tree.other_place = make_place(tree.thies_parish, "Cathédrale")
    tree.pere = named(priest("pere@sd.sn"), "Jean", "Sarr")
    tree.autre_pere = priest("autre@sd.sn")
    tree.secretaire = person("secretaire@sd.sn")
    tree.fidele = named(person("awa@test.sn"), "Awa Marie", "Diop")
    tree.fidele2 = person("moussa@test.sn")
    nominate(tree.pere, "vicaire_paroissial", tree.saint_dominique)
    nominate(tree.autre_pere, "vicaire_paroissial", tree.saint_dominique)
    nominate(tree.secretaire, "secretaire_paroissial", tree.saint_dominique)
    return tree


def rule(world, **kwargs) -> ConfessionSlotRule:
    fields = {
        "priest": world.pere,
        "place": world.place,
        "weekday": 2,  # mercredi
        "start_time": datetime.time(17, 0),
        "end_time": datetime.time(18, 0),
        "slot_minutes": 15,
        **kwargs,
    }
    return services.rule_create(**fields)


def first_slot(world) -> ConfessionSlot:
    slot = ConfessionSlot.objects.filter(priest=world.pere).order_by("starts_at").first()
    assert slot is not None
    return slot


# --- Règles et génération -----------------------------------------------------------------


@freeze_time(NOW)
def test_rule_generates_four_weeks_of_slots(world):
    rule(world)
    slots = ConfessionSlot.objects.filter(priest=world.pere)
    assert slots.count() == 4 * 4  # 4 mercredis × 4 créneaux de 15 min
    assert {timezone.localtime(s.starts_at).weekday() for s in slots} == {2}
    assert first_slot(world).ends_at - first_slot(world).starts_at == datetime.timedelta(minutes=15)


@freeze_time(NOW)
def test_generation_is_idempotent_and_extends_horizon(world):
    rule(world)
    assert services.slots_generate() == 0
    with freeze_time("2026-10-12 08:00:00"):
        assert services.slots_generate() == 4  # un mercredi de plus entre dans l'horizon
    assert ConfessionSlot.objects.filter(priest=world.pere).count() == 20


@freeze_time(NOW)
def test_rule_respects_validity_period(world):
    rule(world, valid_to=datetime.date(2026, 10, 14))
    assert ConfessionSlot.objects.filter(priest=world.pere).count() == 2 * 4


@freeze_time(NOW)
def test_rule_requires_capability_on_place_node(world):
    with pytest.raises(PermissionDeniedError):
        rule(world, place=world.other_place)
    with pytest.raises(PermissionDeniedError):
        rule(world, priest=world.secretaire)


@freeze_time(NOW)
def test_rule_rejects_inverted_times(world):
    with pytest.raises(ApplicationError):
        rule(world, start_time=datetime.time(18, 0), end_time=datetime.time(17, 0))


@freeze_time(NOW)
def test_rule_deactivate_removes_free_future_slots_but_keeps_bookings(world):
    r = rule(world)
    booked = first_slot(world)
    services.booking_create(slot=booked, person=world.fidele)
    with pytest.raises(PermissionDeniedError):
        services.rule_deactivate(rule=r, actor=world.autre_pere)
    services.rule_deactivate(rule=r, actor=world.pere)
    assert list(ConfessionSlot.objects.filter(priest=world.pere)) == [booked]
    assert ConfessionBooking.objects.get().status == B.RESERVEE


# --- Réservation --------------------------------------------------------------------------


@freeze_time(NOW)
def test_booking_marks_slot_reserved_and_second_booking_conflicts(world):
    rule(world)
    slot = first_slot(world)
    services.booking_create(slot=slot, person=world.fidele)
    slot.refresh_from_db()
    assert slot.status == ConfessionSlot.Status.RESERVE
    with pytest.raises(ConflictError):
        services.booking_create(slot=slot, person=world.fidele2)


@freeze_time(NOW)
def test_booking_limits_active_bookings_per_person(world):
    rule(world)
    slots = list(ConfessionSlot.objects.filter(priest=world.pere).order_by("starts_at")[:3])
    services.booking_create(slot=slots[0], person=world.fidele)
    services.booking_create(slot=slots[1], person=world.fidele)
    with pytest.raises(ApplicationError) as exc:
        services.booking_create(slot=slots[2], person=world.fidele)
    assert exc.value.code == "too_many_bookings"


@freeze_time(NOW)
def test_priest_cannot_book_own_slot_nor_past_slot(world):
    rule(world)
    slot = first_slot(world)
    with pytest.raises(ApplicationError):
        services.booking_create(slot=slot, person=world.pere)
    with freeze_time(slot.starts_at + datetime.timedelta(minutes=1)), pytest.raises(ApplicationError):
        services.booking_create(slot=slot, person=world.fidele)


def test_booking_has_no_content_field():
    """RG-08 : aucun champ où le fidèle pourrait écrire."""
    text_fields = {
        f.name
        for f in ConfessionBooking._meta.get_fields()
        if getattr(f, "get_internal_type", lambda: "")() in ("TextField", "CharField")
    }
    assert text_fields <= {"status", "cancel_message"}


# --- Annulations ---------------------------------------------------------------------------


@freeze_time(NOW)
def test_person_cancels_until_one_hour_before(world):
    rule(world)
    slot = first_slot(world)
    booking = services.booking_create(slot=slot, person=world.fidele)
    with freeze_time(slot.starts_at - datetime.timedelta(minutes=59)), pytest.raises(ApplicationError) as exc:
        services.booking_cancel_by_person(booking=booking, person=world.fidele)
    assert exc.value.code == "cancel_too_late"
    with pytest.raises(PermissionDeniedError):
        services.booking_cancel_by_person(booking=booking, person=world.fidele2)
    services.booking_cancel_by_person(booking=booking, person=world.fidele)
    booking.refresh_from_db()
    slot.refresh_from_db()
    assert booking.status == B.ANNULEE_FIDELE
    assert slot.status == ConfessionSlot.Status.LIBRE
    services.booking_create(slot=slot, person=world.fidele2)  # le créneau est de nouveau réservable


@freeze_time(NOW)
def test_priest_cancels_slot_and_notifies_person(world, mailoutbox, django_capture_on_commit_callbacks):
    rule(world)
    slot = first_slot(world)
    booking = services.booking_create(slot=slot, person=world.fidele)
    with pytest.raises(PermissionDeniedError):
        services.slot_cancel_by_priest(slot=slot, actor=world.autre_pere, message="")
    with django_capture_on_commit_callbacks(execute=True):
        services.slot_cancel_by_priest(slot=slot, actor=world.pere, message="Empêché, désolé.")
    booking.refresh_from_db()
    slot.refresh_from_db()
    assert booking.status == B.ANNULEE_PRETRE
    assert booking.cancel_message == "Empêché, désolé."
    assert slot.status == ConfessionSlot.Status.BLOQUE
    assert Notification.objects.filter(user=world.fidele, event_type="confessions.cancelled").exists()
    assert [m.to for m in mailoutbox] == [["awa@test.sn"]]
    assert "confession" not in mailoutbox[0].subject.lower()  # objet discret


@freeze_time(NOW)
def test_attendance_only_after_start_and_by_slot_priest(world):
    rule(world)
    slot = first_slot(world)
    booking = services.booking_create(slot=slot, person=world.fidele)
    with pytest.raises(ApplicationError):
        services.booking_attendance_set(booking=booking, actor=world.pere, attended=True)
    with freeze_time(slot.starts_at + datetime.timedelta(minutes=5)):
        with pytest.raises(PermissionDeniedError):
            services.booking_attendance_set(booking=booking, actor=world.autre_pere, attended=True)
        services.booking_attendance_set(booking=booking, actor=world.pere, attended=False)
    booking.refresh_from_db()
    assert booking.status == B.ABSENT


# --- Rappels -----------------------------------------------------------------------------


@freeze_time(NOW)
def test_reminders_day_before_then_two_hours_before_once_each(world):
    rule(world)
    slot = first_slot(world)  # mercredi 7/10 17:00
    services.booking_create(slot=slot, person=world.fidele)
    with freeze_time(slot.starts_at - datetime.timedelta(hours=20)):
        assert services.bookings_remind() == 1
        assert services.bookings_remind() == 0
    with freeze_time(slot.starts_at - datetime.timedelta(hours=1)):
        assert services.bookings_remind() == 1
        assert services.bookings_remind() == 0
    assert Notification.objects.filter(user=world.fidele, event_type="confessions.reminder").count() == 2


@freeze_time(NOW)
def test_no_reminder_for_cancelled_booking(world):
    rule(world)
    slot = first_slot(world)
    booking = services.booking_create(slot=slot, person=world.fidele)
    services.booking_cancel_by_person(booking=booking, person=world.fidele)
    with freeze_time(slot.starts_at - datetime.timedelta(hours=20)):
        assert services.bookings_remind() == 0


# --- API ---------------------------------------------------------------------------------


@freeze_time(NOW)
def test_api_person_flow(world):
    rule(world)
    client = client_for(world.fidele)
    listing = client.get("/api/v1/confessions/slots/", {"node": str(world.saint_dominique.pk)})
    assert listing.status_code == 200
    assert listing.data["count"] == 16
    slot_id = listing.data["results"][0]["id"]
    assert listing.data["results"][0]["priest_name"] == "Jean Sarr"

    created = client.post("/api/v1/confessions/bookings/", {"slot_id": slot_id}, format="json")
    assert created.status_code == 201
    assert created.data["can_cancel"] is True
    conflict = client_for(world.fidele2).post("/api/v1/confessions/bookings/", {"slot_id": slot_id}, format="json")
    assert conflict.status_code == 409
    assert conflict.data["error"]["code"] == "slot_taken"

    mine = client.get("/api/v1/me/confession-bookings/")
    assert mine.status_code == 200 and mine.data["count"] == 1
    cancelled = client.post(f"/api/v1/confessions/bookings/{created.data['id']}/cancel/")
    assert cancelled.status_code == 200 and cancelled.data["status"] == B.ANNULEE_FIDELE
    other = client_for(world.fidele2).post(f"/api/v1/confessions/bookings/{created.data['id']}/cancel/")
    assert other.status_code == 404


@freeze_time(NOW)
def test_api_booking_rejects_unknown_fields_silently_no_content_stored(world):
    rule(world)
    slot = first_slot(world)
    response = client_for(world.fidele).post(
        "/api/v1/confessions/bookings/", {"slot_id": slot.pk, "message": "mes péchés…"}, format="json"
    )
    assert response.status_code == 201
    assert "mes péchés" not in str(ConfessionBooking.objects.values().get())


@freeze_time(NOW)
def test_api_staff_rules(world):
    client = client_for(world.pere)
    created = client.post(
        "/api/v1/staff/confessions/rules/",
        {"place_id": world.place.pk, "weekday": 5, "start_time": "10:00", "end_time": "11:00"},
        format="json",
    )
    assert created.status_code == 201
    assert client.get("/api/v1/staff/confessions/rules/").data[0]["id"] == created.data["id"]
    assert client_for(world.fidele).get("/api/v1/staff/confessions/rules/").status_code == 403
    assert (
        client_for(world.autre_pere).delete(f"/api/v1/staff/confessions/rules/{created.data['id']}/").status_code == 404
    )
    assert client.delete(f"/api/v1/staff/confessions/rules/{created.data['id']}/").status_code == 204


@freeze_time(NOW)
def test_api_planning_nominative_for_priest_initials_for_secretariat(world):
    rule(world)
    services.booking_create(slot=first_slot(world), person=world.fidele)

    own = client_for(world.pere).get("/api/v1/staff/confessions/planning/")
    assert own.status_code == 200
    booked = [s for s in own.data if s["booking"]]
    assert booked[0]["booking"]["person"] == "Awa Marie Diop"

    secretariat = client_for(world.secretaire).get("/api/v1/staff/confessions/planning/")
    assert secretariat.status_code == 200
    booked = [s for s in secretariat.data if s["booking"]]
    assert booked[0]["booking"]["person"] == "A. D."

    colleague = client_for(world.autre_pere).get("/api/v1/staff/confessions/planning/")
    assert all(s["priest_id"] == world.autre_pere.pk for s in colleague.data)  # pas le planning des autres
    assert client_for(world.fidele).get("/api/v1/staff/confessions/planning/").status_code == 403


@freeze_time(NOW)
def test_api_priest_cancel_and_attendance(world):
    rule(world)
    slot = first_slot(world)
    booking = services.booking_create(slot=slot, person=world.fidele)
    client = client_for(world.pere)
    assert client_for(world.autre_pere).post(f"/api/v1/staff/confessions/slots/{slot.pk}/cancel/").status_code == 404
    with freeze_time(slot.starts_at + datetime.timedelta(minutes=5)):
        response = client.post(
            f"/api/v1/staff/confessions/bookings/{booking.pk}/attendance/", {"attended": True}, format="json"
        )
    assert response.status_code == 204
    other_slot = ConfessionSlot.objects.filter(priest=world.pere, status="libre").first()
    response = client.post(f"/api/v1/staff/confessions/slots/{other_slot.pk}/cancel/", {"message": ""}, format="json")
    assert response.status_code == 200 and response.data["status"] == "bloque"


def test_initials():
    class P:
        first_name, last_name = "awa marie", "diop"

    class U:
        profile = P()

    assert initials(U()) == "A. D."
