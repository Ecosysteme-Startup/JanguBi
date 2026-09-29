"""Dons et quêtes (ADR-017) : six capacités, l'office d'économe paroissial, et les capacités
« dons » des offices existants (SRS §6.2, §6.3).

Copie FIGÉE au 27/09/2026 (une migration ne dépend pas du code applicatif). Idempotente :
n'ajoute que ce qui manque. Le retour arrière retire les capacités « dons » et l'office
d'économe paroissial s'il n'a aucune nomination.
"""

from django.db import migrations

CAPABILITIES = [
    ("dons.voir_fonds", "Voir les fonds, la synthèse et les opérations (noms masqués)"),
    ("dons.gerer_fonds", "Créer, publier et clore les fonds et campagnes"),
    ("dons.saisir_quete", "Saisir et valider les quêtes en espèces"),
    ("dons.voir_donateurs", "Voir le nom des donateurs non anonymes"),
    ("dons.exporter", "Export comptable et rapprochement"),
    ("dons.definir_quete_imperee", "Définir une quête impérée et suivre ses agrégats"),
]
PAROISSE = ["dons.voir_fonds", "dons.gerer_fonds", "dons.saisir_quete", "dons.voir_donateurs", "dons.exporter"]
OFFICE_CAPABILITIES = {
    "cure": PAROISSE,
    "cure_in_solidum": PAROISSE,
    "secretaire_paroissial": ["dons.voir_fonds", "dons.saisir_quete"],
    "eveque_diocesain": ["dons.definir_quete_imperee"],
    "econome_diocesain": ["dons.definir_quete_imperee"],
}
ECONOME = {
    "code": "econome_paroissial",
    "label": "Économe paroissial",
    "node_types": ["paroisse", "quasi_paroisse"],
    "appointed_by": ["cure", "cure_in_solidum"],
    "capabilities": ["tableau_bord.voir", *PAROISSE],
}


def forward(apps, schema_editor):
    Capability = apps.get_model("hierarchy", "Capability")
    OfficeType = apps.get_model("hierarchy", "OfficeType")
    NodeType = apps.get_model("hierarchy", "NodeType")

    for code, label in CAPABILITIES:
        Capability.objects.get_or_create(code=code, defaults={"label": label, "domain": "dons"})

    for office_code, codes in OFFICE_CAPABILITIES.items():
        office = OfficeType.objects.filter(code=office_code).first()
        if office is not None:
            office.capabilities.add(*Capability.objects.filter(code__in=codes))

    econome, created = OfficeType.objects.get_or_create(
        code=ECONOME["code"],
        defaults={
            "label": ECONOME["label"],
            "required_order": "aucun",
            "cardinality": "one",
            "appointed_by_platform": False,
            "inherits_down": True,
            "is_system": True,
        },
    )
    econome.node_types.add(*NodeType.objects.filter(code__in=ECONOME["node_types"]))
    econome.capabilities.add(*Capability.objects.filter(code__in=ECONOME["capabilities"]))
    econome.appointed_by.add(*OfficeType.objects.filter(code__in=ECONOME["appointed_by"]))


def backward(apps, schema_editor):
    Capability = apps.get_model("hierarchy", "Capability")
    OfficeType = apps.get_model("hierarchy", "OfficeType")
    OfficeAssignment = apps.get_model("hierarchy", "OfficeAssignment")

    if not OfficeAssignment.objects.filter(office_type__code=ECONOME["code"]).exists():
        OfficeType.objects.filter(code=ECONOME["code"]).delete()
    Capability.objects.filter(code__in=[c for c, _ in CAPABILITIES]).delete()


class Migration(migrations.Migration):
    dependencies = [("hierarchy", "0008_office_qualities")]

    operations = [migrations.RunPython(forward, backward)]
