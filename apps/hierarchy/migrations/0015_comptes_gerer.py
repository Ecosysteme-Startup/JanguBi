"""Administration des comptes (docs/ADMIN-KEYCLOAK.md) : capacité ``comptes.gerer`` et son
attribution aux offices déjà chargés (évêque diocésain, vicaire général, chancelier, curés).

Copie FIGÉE (une migration ne dépend pas du code applicatif). Idempotente.
"""

from django.db import migrations

CODE = "comptes.gerer"
CAPABILITIES = [(CODE, "Créer et gérer les comptes de son périmètre", "offices")]
OFFICE_CAPABILITIES = {
    code: [CODE] for code in ("eveque_diocesain", "vicaire_general", "chancelier", "cure", "cure_in_solidum")
}
OFFICES = list(OFFICE_CAPABILITIES)


def forward(apps, schema_editor):
    Capability = apps.get_model("hierarchy", "Capability")
    OfficeType = apps.get_model("hierarchy", "OfficeType")
    capability, _ = Capability.objects.get_or_create(
        code=CODE, defaults={"label": "Créer et gérer les comptes de son périmètre", "domain": "offices"}
    )
    for office in OfficeType.objects.filter(code__in=OFFICES):
        office.capabilities.add(capability)


def backward(apps, schema_editor):
    apps.get_model("hierarchy", "Capability").objects.filter(code=CODE).delete()


class Migration(migrations.Migration):
    dependencies = [("hierarchy", "0014_v1_routes_capacites")]

    operations = [migrations.RunPython(forward, backward)]
