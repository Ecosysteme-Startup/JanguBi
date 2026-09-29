"""Intentions de messe (lot V1-routes).

Le fidèle demande ; le secrétariat (``intentions.gerer`` sur la paroisse) planifie, refuse avec
un motif, puis marque l'intention célébrée. Aucun montant, aucun paiement : l'offrande se remet à
la paroisse. Les notifications ne contiennent jamais le texte de l'intention.
"""

import datetime
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.exceptions import ApplicationError, PermissionDeniedError
from apps.hierarchy import authz
from apps.hierarchy.audit import audit_log
from apps.hierarchy.models import Node, PlaceOfWorship
from apps.intentions.enums import OPEN_STATUSES, IntentionStatus
from apps.intentions.models import IntentionSettings, MassCapOverride, MassIntention

PARISH_TYPES = ("paroisse", "quasi_paroisse")
MAX_OPEN_PER_PERSON = 10
HORIZON_DAYS = 366


def _notify(*, user_ids: list[Any], intention: MassIntention, event: str) -> None:
    from apps.messaging.services_notifications import people_notify

    payload = {
        "intention_id": str(intention.pk),
        "status": intention.status,
        "node_id": str(intention.node_id),
        "date": d.isoformat() if (d := intention.scheduled_date or intention.requested_date) else None,
    }
    people_notify(user_ids=user_ids, topic=None, event_type=f"intention.{event}", payload=payload)


def _secretariat_ids(node: Node) -> list[Any]:
    from apps.hierarchy.selectors_offices import capability_holders

    return list(
        capability_holders(node=node, capability="intentions.gerer", direct_only=True).values_list("pk", flat=True)
    )


def _place_check(node: Node, place: PlaceOfWorship | None) -> None:
    if place is not None and place.node_id != node.pk:
        raise ApplicationError("Ce lieu n'appartient pas à la paroisse.", code="place_outside")


def _date_check(day: datetime.date) -> None:
    today = timezone.localdate()
    if day < today:
        raise ApplicationError("La date de la messe est passée.", code="date_past")
    if day > today + datetime.timedelta(days=HORIZON_DAYS):
        raise ApplicationError("Choisissez une date dans l'année qui vient.", code="date_too_far")


@transaction.atomic
def intention_create(
    *,
    requester: Any,
    node: Node,
    kind: str,
    intention: str,
    requested_date: datetime.date | None = None,
    requested_mass: str = "",
    place: PlaceOfWorship | None = None,
    is_anonymous: bool = False,
) -> MassIntention:
    if node.type.code not in PARISH_TYPES:
        raise ApplicationError("Une intention se demande à une paroisse.", code="not_a_parish")
    if not node.is_active_on_platform:
        raise ApplicationError("Cette paroisse ne reçoit pas encore d'intentions par Jàngu Bi.", code="parish_inactive")
    _place_check(node, place)
    if requested_date is not None:
        _date_check(requested_date)
    text = " ".join((intention or "").split())
    if not text:
        raise ApplicationError("Écrivez l'intention.", code="intention_required")
    if MassIntention.objects.filter(requester=requester, status__in=OPEN_STATUSES).count() >= MAX_OPEN_PER_PERSON:
        raise ApplicationError(
            "Vous avez déjà plusieurs intentions en attente. Le secrétariat de la paroisse vous répondra.",
            code="too_many_open",
        )
    obj = MassIntention.objects.create(
        requester=requester,
        node=node,
        place=place,
        kind=kind,
        intention=text[:500],
        is_anonymous=is_anonymous,
        requested_date=requested_date,
        requested_mass=requested_mass.strip(),
    )
    audit_log(actor=requester, action="intention.demande", target=obj, node=node)
    _notify(user_ids=_secretariat_ids(node), intention=obj, event="recue")
    return obj


@transaction.atomic
def intention_cancel(*, intention: MassIntention, requester: Any) -> MassIntention:
    obj = MassIntention.objects.select_for_update().get(pk=intention.pk)
    if obj.requester_id != requester.pk:
        raise PermissionDeniedError("Cette intention ne vous appartient pas.", code="not_owner")
    if obj.status not in OPEN_STATUSES:
        raise ApplicationError("Cette intention n'est plus modifiable.", code="invalid_transition")
    obj.status = IntentionStatus.ANNULEE
    obj.cancelled_at = timezone.now()
    obj.save(update_fields=["status", "cancelled_at", "updated_at"])
    audit_log(actor=requester, action="intention.annulation", target=obj, node=obj.node)
    _notify(user_ids=_secretariat_ids(obj.node), intention=obj, event="annulee")
    return obj


def _lock_for_staff(intention: MassIntention, actor: Any) -> MassIntention:
    obj = MassIntention.objects.select_for_update().select_related("node").get(pk=intention.pk)
    if not authz.peut(actor, "intentions.gerer", obj.node):
        raise PermissionDeniedError("Vous ne gérez pas les intentions de cette paroisse.", code="intentions_forbidden")
    return obj


@transaction.atomic
def intention_schedule(
    *,
    intention: MassIntention,
    actor: Any,
    scheduled_date: datetime.date,
    scheduled_mass: str = "",
    scheduled_time: datetime.time | None = None,
    place: PlaceOfWorship | None = None,
) -> MassIntention:
    """Planifie (ou déplace) l'intention à une messe ; le fidèle est prévenu.

    Avec ``scheduled_time``, la messe (lieu, date, heure) ne peut dépasser le plafond de la paroisse.
    """
    obj = _lock_for_staff(intention, actor)
    if obj.status not in OPEN_STATUSES:
        raise ApplicationError("Cette intention n'est plus modifiable.", code="invalid_transition")
    _place_check(obj.node, place)
    _date_check(scheduled_date)
    if scheduled_time is not None:
        target_place = place or obj.place
        if target_place is None:
            raise ApplicationError("Indiquez le lieu de la messe.", code="place_required")
        taken = (
            MassIntention.objects.filter(
                node=obj.node,
                scheduled_date=scheduled_date,
                scheduled_time=scheduled_time,
                place=target_place,
                status__in=(IntentionStatus.PLANIFIEE, IntentionStatus.CELEBREE),
            )
            .exclude(pk=obj.pk)
            .count()
        )
        cap, _ = effective_cap(node=obj.node, place=target_place, day=scheduled_date, start_time=scheduled_time)
        if cap is not None and taken >= cap:
            raise ApplicationError("Cette messe a déjà toutes ses intentions.", code="mass_full")
    moved = obj.status == IntentionStatus.PLANIFIEE
    obj.status = IntentionStatus.PLANIFIEE
    obj.scheduled_date = scheduled_date
    obj.scheduled_mass = scheduled_mass.strip()
    obj.scheduled_time = scheduled_time
    if place is not None:
        obj.place = place
    obj.decided_by = actor
    obj.decided_at = timezone.now()
    obj.save()
    audit_log(
        actor=actor,
        action="intention.planification",
        target=obj,
        node=obj.node,
        metadata={"date": scheduled_date.isoformat(), "deplacee": moved},
    )
    if obj.requester_id:
        _notify(user_ids=[obj.requester_id], intention=obj, event="planifiee")
    return obj


@transaction.atomic
def intention_decline(*, intention: MassIntention, actor: Any, reason: str) -> MassIntention:
    obj = _lock_for_staff(intention, actor)
    if obj.status not in OPEN_STATUSES:
        raise ApplicationError("Cette intention n'est plus modifiable.", code="invalid_transition")
    reason = " ".join((reason or "").split())
    if not reason:
        raise ApplicationError("Indiquez le motif du refus.", code="reason_required")
    obj.status = IntentionStatus.REFUSEE
    obj.refusal_reason = reason[:300]
    obj.decided_by = actor
    obj.decided_at = timezone.now()
    obj.save(update_fields=["status", "refusal_reason", "decided_by", "decided_at", "updated_at"])
    audit_log(actor=actor, action="intention.refus", target=obj, node=obj.node)
    if obj.requester_id:
        _notify(user_ids=[obj.requester_id], intention=obj, event="refusee")
    return obj


@transaction.atomic
def intention_celebrate(*, intention: MassIntention, actor: Any) -> MassIntention:
    obj = _lock_for_staff(intention, actor)
    if obj.status != IntentionStatus.PLANIFIEE:
        raise ApplicationError("Seule une intention planifiée peut être marquée célébrée.", code="invalid_transition")
    if obj.scheduled_date and obj.scheduled_date > timezone.localdate():
        raise ApplicationError("La messe n'a pas encore eu lieu.", code="not_yet")
    obj.status = IntentionStatus.CELEBREE
    obj.celebrated_at = timezone.now()
    obj.save(update_fields=["status", "celebrated_at", "updated_at"])
    audit_log(actor=actor, action="intention.celebration", target=obj, node=obj.node)
    if obj.requester_id:
        _notify(user_ids=[obj.requester_id], intention=obj, event="celebree")
    return obj


def intentions_forget(*, user: Any) -> int:
    """Suppression du compte (EF-CONF-03) : les intentions ouvertes sont annulées et toutes sont
    détachées de la personne (la paroisse garde la trace d'une messe célébrée, sans son nom)."""
    now = timezone.now()
    MassIntention.objects.filter(requester=user, status__in=OPEN_STATUSES).update(
        status=IntentionStatus.ANNULEE, cancelled_at=now, updated_at=now
    )
    return MassIntention.objects.filter(requester=user).update(requester=None, is_anonymous=True, updated_at=now)


def max_per_mass(*, node: Node) -> int | None:
    """Plafond de la paroisse : 5 sans réglage, ``None`` = sans plafond."""
    from apps.intentions.models import DEFAULT_MAX_PER_MASS

    row = IntentionSettings.objects.filter(node=node).values_list("max_per_mass", flat=True)
    return row[0] if row else DEFAULT_MAX_PER_MASS


def _cap_check(value: int | None) -> None:
    if value is not None and not 1 <= value <= 50:
        raise ApplicationError("Le plafond va de 1 à 50 intentions par messe.", code="max_invalid")


def _forbid_unless_manager(actor: Any, node: Node) -> None:
    if not authz.peut(actor, "intentions.gerer", node):
        raise PermissionDeniedError("Vous ne gérez pas les intentions de cette paroisse.", code="intentions_forbidden")


def cap_overrides(*, node: Node, day: datetime.date) -> dict[tuple[int, datetime.time], tuple[int | None, str]]:
    """Plafonds propres aux messes du jour : {(lieu, heure): (plafond, "date" | "horaire")}."""
    out: dict[tuple[int, datetime.time], tuple[int | None, str]] = {}
    rows = MassCapOverride.objects.filter(node=node).filter(Q(date=day) | Q(date__isnull=True, weekday=day.weekday()))
    for row in sorted(rows, key=lambda r: r.date is not None):  # la messe datée l'emporte
        out[(row.place_id, row.start_time)] = (row.max_intentions, "date" if row.date else "horaire")
    return out


def effective_cap(
    *, node: Node, place: PlaceOfWorship, day: datetime.date, start_time: datetime.time
) -> tuple[int | None, str]:
    """Plafond appliqué à une messe et sa source (``date``, ``horaire`` ou ``paroisse``)."""
    found = cap_overrides(node=node, day=day).get((place.pk, start_time))
    return found if found is not None else (max_per_mass(node=node), "paroisse")


@transaction.atomic
def intention_settings_update(*, node: Node, actor: Any, max_per_mass: int | None) -> IntentionSettings:
    _forbid_unless_manager(actor, node)
    _cap_check(max_per_mass)
    obj, _ = IntentionSettings.objects.update_or_create(node=node, defaults={"max_per_mass": max_per_mass})
    audit_log(actor=actor, action="intention.reglages", target=obj, node=node, metadata={"max_per_mass": max_per_mass})
    return obj


@transaction.atomic
def mass_cap_set(
    *,
    node: Node,
    actor: Any,
    place: PlaceOfWorship,
    start_time: datetime.time,
    max_intentions: int | None,
    weekday: int | None = None,
    date: datetime.date | None = None,
) -> MassCapOverride:
    """Fixe le plafond d'une messe (horaire hebdomadaire ou messe datée) ; ``None`` = sans plafond."""
    _forbid_unless_manager(actor, node)
    _place_check(node, place)
    _cap_check(max_intentions)
    if (weekday is None) == (date is None):
        raise ApplicationError("Indiquez soit le jour de la semaine, soit la date de la messe.", code="weekday_or_date")
    if weekday is not None and not 0 <= weekday <= 6:
        raise ApplicationError("Jour de la semaine invalide (0 = lundi … 6 = dimanche).", code="weekday_invalid")
    obj, _ = MassCapOverride.objects.update_or_create(
        place=place,
        start_time=start_time,
        weekday=weekday,
        date=date,
        defaults={"node": node, "max_intentions": max_intentions},
    )
    audit_log(
        actor=actor,
        action="intention.plafond_messe",
        target=obj,
        node=node,
        metadata={"max_intentions": max_intentions, "weekday": weekday, "date": date.isoformat() if date else None},
    )
    return obj


@transaction.atomic
def mass_cap_clear(
    *,
    node: Node,
    actor: Any,
    place: PlaceOfWorship,
    start_time: datetime.time,
    weekday: int | None = None,
    date: datetime.date | None = None,
) -> None:
    """Retire le plafond propre à la messe : le réglage de la paroisse s'applique de nouveau."""
    _forbid_unless_manager(actor, node)
    _place_check(node, place)
    deleted, _ = MassCapOverride.objects.filter(
        node=node, place=place, start_time=start_time, weekday=weekday, date=date
    ).delete()
    if deleted:
        audit_log(actor=actor, action="intention.plafond_messe", target=place, node=node, metadata={"retire": True})
