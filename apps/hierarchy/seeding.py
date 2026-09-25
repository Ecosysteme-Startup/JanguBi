"""Chargement d'un profil de paramétrage (EF-HIE-07). Idempotent.

Un nœud existant est retrouvé par son code, ou à défaut par (parent, type, nom) :
un nœud migré depuis ``org`` (même nom, autre code) n'est donc pas dupliqué.
"""

from dataclasses import dataclass, field

from django.db import transaction

from apps.core.exceptions import ApplicationError
from apps.hierarchy.models import MassSchedule, Node, NodeType, PlaceOfWorship
from apps.hierarchy.profiles import PROFILES, NodeSpec, Profile
from apps.hierarchy.services import node_create, place_create


@dataclass
class SeedReport:
    created: dict[str, int] = field(default_factory=lambda: {"node_types": 0, "nodes": 0, "places": 0, "schedules": 0})

    def bump(self, key: str) -> None:
        self.created[key] += 1


def _node_find(*, spec: NodeSpec, parent: Node | None) -> Node | None:
    node = Node.objects.filter(code=spec["code"]).first()
    if node is not None:
        return node
    candidates = Node.objects.filter(type__code=spec["type"], name__iexact=spec["name"])
    if parent is None:
        candidates = candidates.filter(depth=1)
    else:
        candidates = candidates.filter(path__startswith=parent.path, depth=parent.depth + 1)
    return candidates.first()


def _profile(profile: str) -> Profile:
    if profile not in PROFILES:
        raise ApplicationError(f"Profil inconnu : « {profile} ».", {"profiles": sorted(PROFILES)}, code="unknown_profile")
    return PROFILES[profile]


@transaction.atomic
def node_types_load(*, profile: str, report: SeedReport | None = None) -> dict[str, NodeType]:
    """Charge (ou complète) le catalogue des types de nœuds d'un profil."""
    data = _profile(profile)
    report = report or SeedReport()
    types: dict[str, NodeType] = {}
    for t in data["node_types"]:
        obj, created = NodeType.objects.get_or_create(
            code=t["code"],
            defaults={
                "label": t["label"],
                "is_territorial": t["is_territorial"],
                "holds_registers": t["holds_registers"],
                "order": t["order"],
            },
        )
        types[t["code"]] = obj
        if created:
            report.bump("node_types")
    for t in data["node_types"]:
        types[t["code"]].allowed_parent_types.add(*[types[p] for p in t["parents"]])
    return types


@transaction.atomic
def hierarchy_profile_load(*, profile: str) -> SeedReport:
    data = _profile(profile)
    report = SeedReport()
    types = node_types_load(profile=profile, report=report)

    nodes: dict[str, Node] = {}
    for spec in data["nodes"]:
        parent_code = spec.get("parent")
        parent = nodes[parent_code] if parent_code else None
        node = _node_find(spec=spec, parent=parent)
        if node is None:
            node = node_create(
                node_type=types[spec["type"]],
                name=spec["name"],
                parent=parent,
                code=spec["code"],
                city=spec.get("city", ""),
                is_active_on_platform=spec.get("is_active_on_platform", False),
            )
            report.bump("nodes")
        elif spec.get("is_active_on_platform") and not node.is_active_on_platform:
            node.is_active_on_platform = True
            node.save(update_fields=["is_active_on_platform", "updated_at"])
        nodes[spec["code"]] = Node.objects.get(pk=node.pk)

    places: dict[str, PlaceOfWorship] = {}
    for p in data["places"]:
        node = nodes[p["node"]]
        place = PlaceOfWorship.objects.filter(node=node, name__iexact=p["name"]).first()
        if place is None:
            has_main = PlaceOfWorship.objects.filter(node=node, is_main=True).exists()
            place = place_create(
                node=node, name=p["name"], kind=p["kind"], is_main=p["is_main"] and not has_main, city=p["city"]
            )
            report.bump("places")
        places[p["name"]] = place

    for s in data["schedules"]:
        place = places[s["place"]]
        for weekday in s["weekdays"]:
            _, created = MassSchedule.objects.get_or_create(
                place=place,
                kind=s["kind"],
                weekday=weekday,
                start_time=s["start_time"],
                defaults={"end_time": s.get("end_time")},
            )
            if created:
                report.bump("schedules")
    return report
