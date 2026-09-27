"""Dons (V2, décision du 27/09/2026) : capacité ``dons.voir_agregats`` — agrégats des dons au-dessus
de la paroisse (diocèse, doyenné), montants arrondis au millier, aucun nom, ordre alphabétique.

Copie FIGÉE (une migration ne dépend pas du code applicatif). Idempotente. Retour arrière : la
capacité est retirée.
"""

from django.db import migrations

CAPABILITIES = [
    ("dons.voir_agregats", "Voir les agrégats des dons des paroisses (arrondis, sans nom)"),
]
OFFICE_CAPABILITIES = {
    "eveque_diocesain": ["dons.voir_agregats"],
    "econome_diocesain": ["dons.voir_agregats"],
}


def forward(apps, schema_editor):
    Capability = apps.get_model("hierarchy", "Capability")
    OfficeType = apps.get_model("hierarchy", "OfficeType")
    for code, label in CAPABILITIES:
        Capability.objects.get_or_create(code=code, defaults={"label": label, "domain": "dons"})
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
