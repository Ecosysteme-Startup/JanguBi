"""Sonothèque paroissiale (plan suite V2, §5) : capacités ``audio.publier`` et ``audio.moderer``
et leur attribution aux offices existants.

Copie FIGÉE au 27/09/2026 (une migration ne dépend pas du code applicatif). Idempotente :
n'ajoute que ce qui manque. Le retour arrière retire les deux capacités (et leurs liens).
"""

from django.db import migrations

CAPABILITIES = [
    ("audio.publier", "Publier des enregistrements dans la sonothèque"),
    ("audio.moderer", "Modérer la sonothèque (signalements, retrait)"),
]
OFFICE_CAPABILITIES = {
    "eveque_diocesain": ["audio.publier", "audio.moderer"],
    "cure": ["audio.publier", "audio.moderer"],
    "cure_in_solidum": ["audio.publier", "audio.moderer"],
    "vicaire_paroissial": ["audio.publier"],
    "secretaire_paroissial": ["audio.publier"],
    "referent_numerique": ["audio.publier"],
    "aumonier": ["audio.publier"],
    "delegue_numerique_diocesain": ["audio.publier", "audio.moderer"],
}


def forward(apps, schema_editor):
    Capability = apps.get_model("hierarchy", "Capability")
    OfficeType = apps.get_model("hierarchy", "OfficeType")

    for code, label in CAPABILITIES:
        Capability.objects.get_or_create(code=code, defaults={"label": label, "domain": "audio"})

    for office_code, codes in OFFICE_CAPABILITIES.items():
        office = OfficeType.objects.filter(code=office_code).first()
        if office is not None:
            office.capabilities.add(*Capability.objects.filter(code__in=codes))


def backward(apps, schema_editor):
    Capability = apps.get_model("hierarchy", "Capability")
    Capability.objects.filter(code__in=[c for c, _ in CAPABILITIES]).delete()


class Migration(migrations.Migration):
    dependencies = [("hierarchy", "0009_dons_capacites")]

    operations = [migrations.RunPython(forward, backward)]
