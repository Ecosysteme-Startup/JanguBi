"""Chargement du catalogue des capacités et des offices.

Écrit contre des classes de modèles passées en argument : la même fonction sert
à la migration de données (modèles historiques) et au code applicatif.
Idempotent ; n'efface jamais une capacité ni un office existant.
"""

from typing import Any

from apps.hierarchy.profiles import CAPABILITIES, OFFICES


def load_offices_catalogue(*, Capability: Any, OfficeType: Any, NodeType: Any) -> dict[str, int]:
    created = {"capabilities": 0, "office_types": 0}
    capabilities = {}
    for c in CAPABILITIES:
        obj, was_created = Capability.objects.get_or_create(
            code=c["code"], defaults={"label": c["label"], "domain": c["domain"]}
        )
        capabilities[c["code"]] = obj
        created["capabilities"] += int(was_created)

    node_types = {t.code: t for t in NodeType.objects.all()}
    offices = {}
    for o in OFFICES:
        obj, was_created = OfficeType.objects.get_or_create(
            code=o["code"],
            defaults={
                "label": o["label"],
                "required_order": o["required_order"],
                "cardinality": o["cardinality"],
                "appointed_by_platform": o["appointed_by_platform"],
                "inherits_down": o["inherits_down"],
                "is_system": True,
            },
        )
        offices[o["code"]] = obj
        if was_created:
            created["office_types"] += 1
            obj.node_types.add(*[node_types[t] for t in o["node_types"] if t in node_types])
            obj.capabilities.add(*[capabilities[c] for c in o["capabilities"]])
    for o in OFFICES:
        if not offices[o["code"]].appointed_by.exists():
            offices[o["code"]].appointed_by.add(*[offices[a] for a in o["appointed_by"]])
    return created
