"""Paroisses multiples (décisions 6-8 du 29/09/2026).

1. Données : chaque ``BaseUser.paroisse_suivie`` devient une appartenance **principale**
   (``joined_at`` = création du compte, faute de mieux). Le champ est gardé (copie de la principale).
2. Capacité ``paroissiens.gerer`` (voir les membres, en retirer) et son attribution aux offices
   existants de la paroisse.

Copie FIGÉE (une migration ne dépend pas du code applicatif). Idempotente. Retour arrière : les
appartenances sont effacées (la paroisse principale reste dans ``paroisse_suivie``) et la capacité
retirée.
"""

from django.db import migrations

CAPABILITIES = [
    ("paroissiens.gerer", "Voir les membres de la paroisse et en retirer"),
]
OFFICE_CAPABILITIES = {
    "cure": ["paroissiens.gerer"],
    "cure_in_solidum": ["paroissiens.gerer"],
    "secretaire_paroissial": ["paroissiens.gerer"],
}


def forward(apps, schema_editor):
    BaseUser = apps.get_model("users", "BaseUser")
    ParishMembership = apps.get_model("hierarchy", "ParishMembership")
    Capability = apps.get_model("hierarchy", "Capability")
    OfficeType = apps.get_model("hierarchy", "OfficeType")

    existing = set(ParishMembership.objects.values_list("user_id", flat=True))
    rows = [
        ParishMembership(user_id=u.pk, node_id=u.paroisse_suivie_id, is_primary=True, joined_at=u.created_at)
        for u in BaseUser.objects.filter(paroisse_suivie__isnull=False).only("pk", "paroisse_suivie_id", "created_at")
        if u.pk not in existing
    ]
    ParishMembership.objects.bulk_create(rows, batch_size=1000)

    for code, label in CAPABILITIES:
        Capability.objects.get_or_create(code=code, defaults={"label": label, "domain": "paroisse"})
    for office_code, codes in OFFICE_CAPABILITIES.items():
        office = OfficeType.objects.filter(code=office_code).first()
        if office is not None:
            office.capabilities.add(*Capability.objects.filter(code__in=codes))


def backward(apps, schema_editor):
    apps.get_model("hierarchy", "ParishMembership").objects.all().delete()
    apps.get_model("hierarchy", "Capability").objects.filter(code__in=[c for c, _ in CAPABILITIES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("hierarchy", "0012_parish_membership"),
        ("users", "0003_presence"),
    ]

    operations = [migrations.RunPython(forward, backward)]
