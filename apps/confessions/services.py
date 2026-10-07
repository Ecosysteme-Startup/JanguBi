"""Rendez-vous de confession en présentiel (SRS §3.7 EF-PRE-10 à 13 ; RG-08).

Autorisation : ``confessions.gerer`` sur le nœud du lieu pour créer une règle, et
seulement pour soi. Un prêtre n'agit que sur ses propres créneaux. Aucun contenu :
le fidèle réserve une heure, rien d'autre.
"""

import datetime
import logging
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.confessions.models import ConfessionBooking, ConfessionSlot, ConfessionSlotRule
from apps.confessions.selectors import PERSON_CANCEL_DEADLINE
from apps.core.exceptions import ApplicationError, ConflictError, PermissionDeniedError
from apps.hierarchy import authz
from apps.hierarchy.audit import audit_log
from apps.hierarchy.models import PlaceOfWorship

logger = logging.getLogger(__name__)

HORIZON_DAYS = 28  # 4 semaines glissantes
MAX_ACTIVE_BOOKINGS = 2  # réservations à venir par personne (anti-accaparement)
REMINDER_DAY = datetime.timedelta(hours=24)
REMINDER_HOURS = datetime.timedelta(hours=2)


# --- Règles -------------------------------------------------------------------------------


@transaction.atomic
def rule_create(
    *,
    priest: Any,
    place: PlaceOfWorship,
    weekday: int,
    start_time: datetime.time,
    end_time: datetime.time,
    slot_minutes: int = 10,
    valid_from: datetime.date | None = None,
    valid_to: datetime.date | None = None,
) -> ConfessionSlotRule:
    if not authz.peut(priest, "confessions.gerer", place.node):
        raise PermissionDeniedError("Vous ne gérez pas de créneaux sur ce lieu.", code="confessions_forbidden")
    if not place.is_active:
        raise ApplicationError("Ce lieu n'est plus actif.", code="place_inactive")
    if end_time <= start_time:
        raise ApplicationError("La fin doit suivre le début.", code="invalid_times")
    if valid_from and valid_to and valid_to < valid_from:
        raise ApplicationError("La période de validité est incohérente.", code="invalid_period")
    rule = ConfessionSlotRule.objects.create(
        priest=priest,
        place=place,
        weekday=weekday,
        start_time=start_time,
        end_time=end_time,
        slot_minutes=slot_minutes,
        valid_from=valid_from,
        valid_to=valid_to,
    )
    _rule_generate(rule=rule, today=timezone.localdate())
    audit_log(actor=priest, action="confessions.regle_creation", target=rule, node=place.node)
    return rule


@transaction.atomic
def rule_deactivate(*, rule: ConfessionSlotRule, actor: Any) -> ConfessionSlotRule:
    """Désactive la règle et retire ses créneaux libres à venir ; les réservations restent."""
    if rule.priest_id != actor.pk:
        raise PermissionDeniedError("Cette règle ne vous appartient pas.", code="not_rule_owner")
    rule.is_active = False
    rule.save(update_fields=["is_active", "updated_at"])
    ConfessionSlot.objects.filter(rule=rule, status=ConfessionSlot.Status.LIBRE, starts_at__gt=timezone.now()).delete()
    audit_log(actor=actor, action="confessions.regle_desactivation", target=rule, node=rule.place.node)
    return rule


def _rule_starts(rule: ConfessionSlotRule, *, today: datetime.date) -> list[datetime.datetime]:
    tz = timezone.get_current_timezone()
    step = datetime.timedelta(minutes=rule.slot_minutes)
    starts = []
    for offset in range(HORIZON_DAYS):
        day = today + datetime.timedelta(days=offset)
        if day.weekday() != rule.weekday:
            continue
        if (rule.valid_from and day < rule.valid_from) or (rule.valid_to and day > rule.valid_to):
            continue
        cursor = datetime.datetime.combine(day, rule.start_time, tzinfo=tz)
        end = datetime.datetime.combine(day, rule.end_time, tzinfo=tz)
        while cursor + step <= end:
            starts.append(cursor)
            cursor += step
    return starts


def _rule_generate(*, rule: ConfessionSlotRule, today: datetime.date) -> int:
    now = timezone.now()
    step = datetime.timedelta(minutes=rule.slot_minutes)
    slots = [
        ConfessionSlot(rule=rule, priest_id=rule.priest_id, place_id=rule.place_id, starts_at=s, ends_at=s + step)
        for s in _rule_starts(rule, today=today)
        if s > now
    ]
    if not slots:
        return 0
    # Idempotent : (prêtre, début) est unique ; deux règles qui se chevauchent ne doublonnent pas.
    # bulk_create(ignore_conflicts) renvoie aussi les objets ignorés : on compte avant et après.
    same_starts = ConfessionSlot.objects.filter(priest_id=rule.priest_id, starts_at__in=[s.starts_at for s in slots])
    before = same_starts.count()
    ConfessionSlot.objects.bulk_create(slots, ignore_conflicts=True)
    return same_starts.count() - before


def slots_generate(*, today: datetime.date | None = None) -> int:
    """Tâche quotidienne : prolonge l'horizon de 4 semaines pour chaque règle active."""
    today = today or timezone.localdate()
    total = 0
    for rule in ConfessionSlotRule.objects.filter(is_active=True, place__is_active=True).iterator():
        try:
            with transaction.atomic():
                total += _rule_generate(rule=rule, today=today)
        except Exception:  # noqa: BLE001 — une règle en erreur ne bloque pas les autres
            logger.exception("confessions.generation_failed", extra={"rule_id": rule.pk})
    return total


# --- Séance ponctuelle (lot V1-routes, G05) --------------------------------------------------

SESSION_MAX_SLOTS = 48


@transaction.atomic
def session_open(
    *,
    actor: Any,
    place: PlaceOfWorship,
    day: datetime.date,
    start_time: datetime.time,
    end_time: datetime.time,
    slot_minutes: int = 10,
    priest: Any = None,
) -> list[ConfessionSlot]:
    """Ouvre une séance ponctuelle (sans règle hebdomadaire) : des créneaux libres de
    ``slot_minutes`` entre ``start_time`` et ``end_time`` le jour ``day``.

    Le confesseur (``priest``, par défaut celui qui ouvre) doit détenir ``confessions.gerer`` sur
    le nœud du lieu ; ouvrir pour un autre prêtre exige aussi ``confessions.gerer`` sur ce nœud.
    Les créneaux déjà existants du prêtre à la même heure sont gardés (idempotent)."""
    priest = priest or actor
    node = place.node
    if not authz.peut(actor, "confessions.gerer", node):
        raise PermissionDeniedError("Vous ne gérez pas de créneaux sur ce lieu.", code="confessions_forbidden")
    if priest.pk != actor.pk and not authz.peut(priest, "confessions.gerer", node):
        raise ApplicationError("Ce prêtre ne confesse pas sur ce lieu.", code="priest_not_confessor")
    if not place.is_active:
        raise ApplicationError("Ce lieu n'est plus actif.", code="place_inactive")
    if end_time <= start_time:
        raise ApplicationError("La fin doit suivre le début.", code="invalid_times")
    today = timezone.localdate()
    if day < today or day > today + datetime.timedelta(days=HORIZON_DAYS * 3):
        raise ApplicationError("Choisissez une date dans les douze semaines à venir.", code="invalid_day")
    tz = timezone.get_current_timezone()
    step = datetime.timedelta(minutes=slot_minutes)
    cursor = datetime.datetime.combine(day, start_time, tzinfo=tz)
    end = datetime.datetime.combine(day, end_time, tzinfo=tz)
    now = timezone.now()
    starts = []
    while cursor + step <= end:
        if cursor > now:
            starts.append(cursor)
        cursor += step
    if not starts:
        raise ApplicationError("Aucun créneau à venir dans cette plage.", code="no_slot")
    if len(starts) > SESSION_MAX_SLOTS:
        raise ApplicationError("Séance trop longue : réduisez la plage.", code="session_too_long")
    ConfessionSlot.objects.bulk_create(
        [ConfessionSlot(priest=priest, place=place, starts_at=s, ends_at=s + step) for s in starts],
        ignore_conflicts=True,
    )
    slots = list(
        ConfessionSlot.objects.filter(priest=priest, place=place, starts_at__in=starts)
        .select_related("place", "priest__profile")
        .order_by("starts_at")
    )
    audit_log(
        actor=actor,
        action="confessions.seance_ouverture",
        target=place,
        node=node,
        metadata={"day": day.isoformat(), "slots": len(slots), "priest_id": str(priest.pk)},
    )
    return slots


# --- Réservations -------------------------------------------------------------------------


@transaction.atomic
def booking_create(*, slot: ConfessionSlot, person: Any) -> ConfessionBooking:
    """Réservation sous verrou du créneau : deux fidèles simultanés → un seul passe, l'autre 409."""
    locked = ConfessionSlot.objects.select_for_update().filter(pk=slot.pk).first()
    if locked is None:
        raise ApplicationError("Créneau introuvable.", code="not_found")
    if locked.priest_id == person.pk:
        raise ApplicationError("Vous ne pouvez pas réserver votre propre créneau.", code="own_slot")
    if locked.starts_at <= timezone.now():
        raise ApplicationError("Ce créneau est passé.", code="slot_past")
    if locked.status != ConfessionSlot.Status.LIBRE:
        raise ConflictError("Ce créneau vient d'être pris. Choisissez-en un autre.", code="slot_taken")
    active = ConfessionBooking.objects.filter(
        person=person, status=ConfessionBooking.Status.RESERVEE, slot__starts_at__gt=timezone.now()
    ).count()
    if active >= MAX_ACTIVE_BOOKINGS:
        raise ApplicationError(
            f"Vous avez déjà {active} rendez-vous à venir.", {"max": MAX_ACTIVE_BOOKINGS}, code="too_many_bookings"
        )
    # JB-WEB-017 : pas de chevauchement horaire. Un fidèle ne peut pas réserver deux
    # rendez-vous qui se recoupent dans le temps (même avec deux prêtres différents).
    overlapping = ConfessionBooking.objects.filter(
        person=person,
        status=ConfessionBooking.Status.RESERVEE,
        slot__starts_at__lt=locked.ends_at,
        slot__ends_at__gt=locked.starts_at,
    ).exists()
    if overlapping:
        raise ConflictError(
            "Vous avez déjà un rendez-vous qui chevauche ce créneau.", code="overlapping_booking"
        )
    try:
        with transaction.atomic():
            booking = ConfessionBooking.objects.create(slot=locked, person=person)
    except IntegrityError as exc:
        raise ConflictError("Ce créneau vient d'être pris.", code="slot_taken") from exc
    locked.status = ConfessionSlot.Status.RESERVE
    locked.save(update_fields=["status", "updated_at"])
    return booking


def _lock_booking(booking: ConfessionBooking) -> ConfessionBooking:
    """Ordre des verrous commun à tout le module : le créneau, PUIS la réservation
    (sinon l'annulation du prêtre et celle du fidèle s'interbloquent)."""
    ConfessionSlot.objects.select_for_update().filter(pk=booking.slot_id).first()
    locked = (
        ConfessionBooking.objects.select_for_update(of=("self",))
        .select_related("slot", "slot__place")
        .filter(pk=booking.pk)
        .first()
    )
    if locked is None:
        raise ApplicationError("Réservation introuvable.", code="not_found")
    return locked


@transaction.atomic
def booking_cancel_by_person(*, booking: ConfessionBooking, person: Any) -> ConfessionBooking:
    locked = _lock_booking(booking)
    if locked.person_id != person.pk:
        raise PermissionDeniedError("Cette réservation ne vous appartient pas.", code="not_booking_owner")
    if locked.status != ConfessionBooking.Status.RESERVEE:
        raise ApplicationError("Cette réservation n'est plus active.", code="booking_not_active")
    now = timezone.now()
    if locked.slot.starts_at - now < PERSON_CANCEL_DEADLINE:
        raise ApplicationError(
            "L'annulation est possible jusqu'à une heure avant le rendez-vous.", code="cancel_too_late"
        )
    locked.status = ConfessionBooking.Status.ANNULEE_FIDELE
    locked.cancelled_at = now
    locked.save(update_fields=["status", "cancelled_at", "updated_at"])
    ConfessionSlot.objects.filter(pk=locked.slot_id, status=ConfessionSlot.Status.RESERVE).update(
        status=ConfessionSlot.Status.LIBRE, updated_at=now
    )
    return locked


@transaction.atomic
def slot_cancel_by_priest(*, slot: ConfessionSlot, actor: Any, message: str = "") -> ConfessionSlot:
    """Le créneau passe ``bloque`` ; le réservant éventuel est prévenu avec le message du prêtre."""
    locked = ConfessionSlot.objects.select_for_update().select_related("place").filter(pk=slot.pk).first()
    if locked is None:
        raise ApplicationError("Créneau introuvable.", code="not_found")
    if locked.priest_id != actor.pk:
        raise PermissionDeniedError("Ce créneau ne vous appartient pas.", code="not_slot_owner")
    if locked.starts_at <= timezone.now():
        raise ApplicationError("Ce créneau est passé.", code="slot_past")
    if locked.status == ConfessionSlot.Status.BLOQUE:
        return locked
    now = timezone.now()
    booking = (
        ConfessionBooking.objects.select_for_update()
        .filter(slot=locked, status=ConfessionBooking.Status.RESERVEE)
        .first()
    )
    if booking is not None:
        booking.status = ConfessionBooking.Status.ANNULEE_PRETRE
        booking.cancelled_at = now
        booking.cancel_message = message[:300]
        booking.save(update_fields=["status", "cancelled_at", "cancel_message", "updated_at"])
        _notify(
            booking=booking,
            slot=locked,
            event_type="confessions.cancelled",
            template="confession_annulation",
            extra={"message": booking.cancel_message},
        )
    locked.status = ConfessionSlot.Status.BLOQUE
    locked.save(update_fields=["status", "updated_at"])
    audit_log(actor=actor, action="confessions.creneau_annulation", target=locked, node=locked.place.node)
    return locked


@transaction.atomic
def booking_attendance_set(*, booking: ConfessionBooking, actor: Any, attended: bool) -> ConfessionBooking:
    locked = _lock_booking(booking)
    if locked.slot.priest_id != actor.pk:
        raise PermissionDeniedError("Ce rendez-vous n'est pas le vôtre.", code="not_slot_owner")
    if locked.slot.starts_at > timezone.now():
        raise ApplicationError("Le rendez-vous n'a pas encore eu lieu.", code="slot_not_started")
    if locked.status not in (
        ConfessionBooking.Status.RESERVEE,
        ConfessionBooking.Status.HONOREE,
        ConfessionBooking.Status.ABSENT,
    ):
        raise ApplicationError("Cette réservation a été annulée.", code="booking_not_active")
    locked.status = ConfessionBooking.Status.HONOREE if attended else ConfessionBooking.Status.ABSENT
    locked.save(update_fields=["status", "updated_at"])
    return locked


# --- Rappels ------------------------------------------------------------------------------


def _notify(
    *,
    booking: ConfessionBooking,
    slot: ConfessionSlot,
    event_type: str,
    template: str,
    extra: dict[str, Any] | None = None,
) -> None:
    from apps.messaging.services_notifications import people_notify

    starts_at = timezone.localtime(slot.starts_at)
    people_notify(
        user_ids=[booking.person_id],
        topic=None,
        event_type=event_type,
        payload={"booking_id": str(booking.pk), "starts_at": starts_at.isoformat(), "place": slot.place.name},
        email_template=template,
        email_context={"starts_at": starts_at, "place": slot.place.name, **(extra or {})},
    )


def bookings_remind(*, now: datetime.datetime | None = None) -> int:
    """Rappels à J-1 et à H-2, une fois chacun. Une réservation par transaction."""
    now = now or timezone.now()
    active = ConfessionBooking.objects.filter(status=ConfessionBooking.Status.RESERVEE, slot__starts_at__gt=now)
    due = [
        ("reminder_hours_sent_at", pk)
        for pk in active.filter(
            reminder_hours_sent_at__isnull=True, slot__starts_at__lte=now + REMINDER_HOURS
        ).values_list("pk", flat=True)
    ] + [
        ("reminder_day_sent_at", pk)
        for pk in active.filter(
            reminder_day_sent_at__isnull=True,
            slot__starts_at__gt=now + REMINDER_HOURS,
            slot__starts_at__lte=now + REMINDER_DAY,
        ).values_list("pk", flat=True)
    ]
    count = 0
    for field, booking_id in due:
        try:
            with transaction.atomic():
                # Pas de verrou sur le créneau ici : skip_locked écarte une réservation en cours
                # d'annulation, reprise au passage suivant (pas d'attente, pas d'interblocage).
                booking = (
                    ConfessionBooking.objects.select_for_update(of=("self",), skip_locked=True)
                    .select_related("slot", "slot__place")
                    .filter(pk=booking_id, status=ConfessionBooking.Status.RESERVEE, **{f"{field}__isnull": True})
                    .first()
                )
                if booking is None:
                    continue
                _notify(
                    booking=booking, slot=booking.slot, event_type="confessions.reminder", template="confession_rappel"
                )
                setattr(booking, field, now)
                if field == "reminder_hours_sent_at":
                    booking.reminder_day_sent_at = booking.reminder_day_sent_at or now  # pas de J-1 après H-2
                booking.save(update_fields=["reminder_day_sent_at", "reminder_hours_sent_at", "updated_at"])
                count += 1
        except Exception:  # noqa: BLE001 — journalisé, repris au prochain passage
            logger.exception("confessions.reminder_failed", extra={"booking_id": booking_id})
    return count
