from datetime import date, time
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.text import slugify

from apps.core.exceptions import ApplicationError
from apps.hierarchy.enums import NodeStatus, PlaceKind, ScheduleKind
from apps.hierarchy.models import MassSchedule, Node, NodeType, PlaceOfWorship, ScheduleException

NODE_UPDATABLE_FIELDS = (
    "name",
    "code",
    "status",
    "address",
    "city",
    "lat",
    "lng",
    "erected_at",
    "is_active_on_platform",
    "located_in",
)
PLACE_UPDATABLE_FIELDS = ("name", "kind", "is_main", "address", "city", "lat", "lng", "is_active")


# --- Nœuds -------------------------------------------------------------------


def node_parent_validate(*, node_type: NodeType, parent: Node | None) -> None:
    """Un type racine n'a pas de parent ; sinon le parent doit être d'un type autorisé (EF-HIE-01)."""
    allowed = list(node_type.allowed_parent_types.all())
    if parent is None:
        if allowed:
            labels = ", ".join(t.label for t in allowed)
            raise ApplicationError(
                f"Un nœud « {node_type.label} » doit avoir un parent ({labels}).",
                {"type": node_type.code},
                code="parent_required",
            )
        return
    if parent.type_id not in {t.id for t in allowed}:
        raise ApplicationError(
            f"Un nœud « {node_type.label} » ne peut pas être rattaché à un nœud « {parent.type.label} ».",
            {"type": node_type.code, "parent_type": parent.type.code},
            code="parent_type_not_allowed",
        )


def node_code_generate(*, name: str, parent: Node | None) -> str:
    base = slugify(name).upper()[:40] or "NOEUD"
    wanted = f"{parent.code}-{base}" if parent is not None else base
    wanted = wanted[:60]
    code, suffix = wanted, 2
    while Node.objects.filter(code=code).exists():
        code = f"{wanted[:57]}-{suffix}"
        suffix += 1
    return code


@transaction.atomic
def node_create(
    *,
    node_type: NodeType,
    name: str,
    parent: Node | None = None,
    code: str | None = None,
    status: str = NodeStatus.ERIGE,
    address: str = "",
    city: str = "",
    lat: Decimal | None = None,
    lng: Decimal | None = None,
    erected_at: date | None = None,
    is_active_on_platform: bool = False,
    located_in: Node | None = None,
) -> Node:
    node_parent_validate(node_type=node_type, parent=parent)
    if code and Node.objects.filter(code=code).exists():
        raise ApplicationError(f"Le code « {code} » est déjà utilisé.", {"code": code}, code="code_taken")

    fields: dict[str, Any] = {
        "type": node_type,
        "name": name,
        "code": code or node_code_generate(name=name, parent=parent),
        "status": status,
        "address": address,
        "city": city,
        "lat": lat,
        "lng": lng,
        "erected_at": erected_at,
        "is_active_on_platform": is_active_on_platform,
        "located_in": located_in,
    }
    if parent is None:
        return Node.add_root(**fields)
    # Relire le parent : son chemin et son nombre d'enfants doivent être à jour.
    return Node.objects.get(pk=parent.pk).add_child(**fields)


@transaction.atomic
def node_update(*, node: Node, data: dict[str, Any]) -> Node:
    unknown = set(data) - set(NODE_UPDATABLE_FIELDS)
    if unknown:
        raise ApplicationError("Champs non modifiables.", {"fields": sorted(unknown)}, code="field_not_updatable")
    if "code" in data and Node.objects.filter(code=data["code"]).exclude(pk=node.pk).exists():
        raise ApplicationError(f"Le code « {data['code']} » est déjà utilisé.", {"code": data["code"]}, code="code_taken")
    if data.get("located_in") is not None and data["located_in"].pk == node.pk:
        raise ApplicationError("Un nœud ne peut pas être situé dans lui-même.", code="invalid_location")

    for field, value in data.items():
        setattr(node, field, value)
    node.save(update_fields=[*data.keys(), "updated_at"] if data else None)
    return node


# --- Lieux de culte ---------------------------------------------------------


def _main_place_check(*, node: Node, exclude: PlaceOfWorship | None = None) -> None:
    # Verrou sur le nœud : deux créations concurrentes d'un lieu principal sont sérialisées.
    Node.objects.select_for_update().filter(pk=node.pk).first()
    others = PlaceOfWorship.objects.filter(node=node, is_main=True)
    if exclude is not None:
        others = others.exclude(pk=exclude.pk)
    if others.exists():
        raise ApplicationError(
            f"« {node.name} » a déjà un lieu de culte principal.", {"node": str(node.pk)}, code="main_place_exists"
        )


def _place_save(place: PlaceOfWorship) -> None:
    try:
        with transaction.atomic():
            place.save()
    except IntegrityError as exc:  # filet : contrainte « un seul lieu principal »
        raise ApplicationError(
            f"« {place.node.name} » a déjà un lieu de culte principal.", code="main_place_exists"
        ) from exc


@transaction.atomic
def place_create(
    *,
    node: Node,
    name: str,
    kind: str = PlaceKind.CHAPELLE,
    is_main: bool = False,
    address: str = "",
    city: str = "",
    lat: Decimal | None = None,
    lng: Decimal | None = None,
) -> PlaceOfWorship:
    if is_main:
        _main_place_check(node=node)
    place = PlaceOfWorship(
        node=node, name=name, kind=kind, is_main=is_main, address=address, city=city, lat=lat, lng=lng
    )
    place.full_clean(validate_constraints=False)
    _place_save(place)
    return place


@transaction.atomic
def place_update(*, place: PlaceOfWorship, data: dict[str, Any]) -> PlaceOfWorship:
    unknown = set(data) - set(PLACE_UPDATABLE_FIELDS)
    if unknown:
        raise ApplicationError("Champs non modifiables.", {"fields": sorted(unknown)}, code="field_not_updatable")
    if data.get("is_main"):
        _main_place_check(node=place.node, exclude=place)
    for field, value in data.items():
        setattr(place, field, value)
    place.full_clean(validate_constraints=False)
    _place_save(place)
    return place


# --- Horaires ----------------------------------------------------------------


def _schedule_build(*, place: PlaceOfWorship, item: dict[str, Any], index: int) -> MassSchedule:
    schedule = MassSchedule(
        place=place,
        kind=item.get("kind", ScheduleKind.MESSE),
        weekday=item["weekday"],
        start_time=item["start_time"],
        end_time=item.get("end_time"),
        language=item.get("language", "fr"),
        note=item.get("note", ""),
        valid_from=item.get("valid_from"),
        valid_to=item.get("valid_to"),
    )
    try:
        schedule.full_clean(exclude=["place"])
    except ValidationError as exc:
        raise ApplicationError(
            f"Horaire n° {index + 1} invalide.", {"index": index, "errors": exc.message_dict}, code="invalid_schedule"
        ) from exc
    if schedule.end_time is not None and schedule.end_time <= schedule.start_time:
        raise ApplicationError(
            f"Horaire n° {index + 1} : la fin doit suivre le début.", {"index": index}, code="invalid_schedule"
        )
    return schedule


@transaction.atomic
def schedule_replace(*, place: PlaceOfWorship, items: list[dict[str, Any]]) -> list[MassSchedule]:
    """Remplace la semaine type d'un lieu de culte (PUT)."""
    schedules = [_schedule_build(place=place, item=item, index=i) for i, item in enumerate(items)]
    MassSchedule.objects.filter(place=place).delete()
    return MassSchedule.objects.bulk_create(schedules)


@transaction.atomic
def schedule_exception_create(
    *,
    place: PlaceOfWorship,
    date: date,
    kind: str = ScheduleKind.MESSE,
    cancelled: bool = False,
    start_time: time | None = None,
    end_time: time | None = None,
    note: str = "",
) -> ScheduleException:
    if not cancelled and start_time is None:
        raise ApplicationError(
            "Un horaire supplémentaire doit avoir une heure de début.", code="exception_needs_time"
        )
    if start_time is not None and end_time is not None and end_time <= start_time:
        raise ApplicationError("La fin doit suivre le début.", code="invalid_schedule")
    try:
        return ScheduleException.objects.create(
            place=place,
            date=date,
            kind=kind,
            cancelled=cancelled,
            start_time=start_time,
            end_time=end_time,
            note=note,
        )
    except IntegrityError as exc:  # pragma: no cover - doublé par la validation ci-dessus
        raise ApplicationError("Exception d'horaire invalide.", code="invalid_schedule") from exc


@transaction.atomic
def schedule_exception_delete(*, exception: ScheduleException) -> None:
    exception.delete()
