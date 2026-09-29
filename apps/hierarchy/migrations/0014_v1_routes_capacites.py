"""Lot V1-routes : capacités ``comptes.valider`` (invitations et validation des comptes du clergé)
et ``intentions.gerer`` (intentions de messe reçues par le secrétariat), et leur attribution aux
offices déjà chargés.

Copie FIGÉE (une migration ne dépend pas du code applicatif). Idempotente. Retour arrière : les
capacités sont retirées.
"""

from django.db import migrations

CAPABILITIES = [
    ("comptes.valider", "Inviter, valider et activer les comptes du clergé", "offices"),
    ("intentions.gerer", "Recevoir et planifier les intentions de messe", "paroisse"),
]
OFFICE_CAPABILITIES = {
    "chancelier": ["comptes.valider"],
    "vicaire_general": ["comptes.valider"],
    "eveque_diocesain": ["comptes.valider", "intentions.gerer"],
    "cure": ["intentions.gerer"],
    "cure_in_solidum": ["intentions.gerer"],
    "secretaire_paroissial": ["intentions.gerer"],
}


def forward(apps, schema_editor):
    Capability = apps.get_model("hierarchy", "Capability")
    OfficeType = apps.get_model("hierarchy", "OfficeType")
    for code, label, domain in CAPABILITIES:
        Capability.objects.get_or_create(code=code, defaults={"label": label, "domain": domain})
    for office_code, codes in OFFICE_CAPABILITIES.items():
        office = OfficeType.objects.filter(code=office_code).first()
        if office is not None:
            office.capabilities.add(*Capability.objects.filter(code__in=codes))


def backward(apps, schema_editor):
    apps.get_model("hierarchy", "Capability").objects.filter(code__in=[c for c, _, _ in CAPABILITIES]).delete()


class Migration(migrations.Migration):
    dependencies = [("hierarchy", "0013_memberships_data")]

    operations = [migrations.RunPython(forward, backward)]
