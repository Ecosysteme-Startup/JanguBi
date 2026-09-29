"""Catalogue des types de nœuds « Sénégal » (copie figée de profiles.SENEGAL_NODE_TYPES)."""

from django.db import migrations

NODE_TYPES = [
    ("province", "Province ecclésiastique", True, False, 10, []),
    ("diocese", "Diocèse", True, False, 20, ["province"]),
    ("zone", "Zone pastorale", True, False, 30, ["diocese"]),
    ("doyenne", "Doyenné", True, False, 40, ["diocese", "zone"]),
    ("paroisse", "Paroisse", True, True, 50, ["doyenne", "zone", "diocese"]),
    ("quasi_paroisse", "Quasi-paroisse / secteur pastoral", True, True, 55, ["doyenne", "zone", "diocese"]),
    ("aumonerie", "Aumônerie", False, False, 60, ["diocese", "zone"]),
    ("ceb", "Communauté ecclésiale de base", True, False, 70, ["paroisse", "quasi_paroisse"]),
    ("mouvement", "Mouvement / association", False, False, 80, ["paroisse", "quasi_paroisse", "diocese"]),
    ("institut", "Institut de vie consacrée", False, False, 100, []),
    ("province_religieuse", "Province religieuse", False, False, 110, ["institut"]),
    ("communaute", "Communauté religieuse", False, False, 120, ["institut", "province_religieuse"]),
]


def seed_types(apps, schema_editor):
    NodeType = apps.get_model("hierarchy", "NodeType")
    by_code = {}
    for code, label, territorial, registers, order, _parents in NODE_TYPES:
        obj, _ = NodeType.objects.get_or_create(
            code=code,
            defaults={"label": label, "is_territorial": territorial, "holds_registers": registers, "order": order},
        )
        by_code[code] = obj
    for code, *_rest, parents in NODE_TYPES:
        by_code[code].allowed_parent_types.add(*[by_code[p] for p in parents])


def unseed_types(apps, schema_editor):
    NodeType = apps.get_model("hierarchy", "NodeType")
    NodeType.objects.filter(code__in=[t[0] for t in NODE_TYPES], nodes__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("hierarchy", "0002_initial")]

    operations = [migrations.RunPython(seed_types, unseed_types)]
