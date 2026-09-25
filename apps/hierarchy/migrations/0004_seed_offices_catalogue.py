"""Catalogue des capacités (fermé) et des offices du profil « Sénégal » (SRS §6.2, §6.3).

Copie FIGÉE du catalogue au 25/09/2026 : une migration ne doit pas dépendre de code
applicatif qui évoluera. Toute évolution du catalogue passe par une nouvelle migration.
"""

from django.db import migrations

# (code, libellé, domaine)
CAPABILITIES = [
    ("structure.gerer", "Créer ou modifier les nœuds et lieux de culte du sous-arbre", "structure"),
    ("horaires.gerer", "Horaires et exceptions des lieux de culte", "structure"),
    ("offices.nommer", "Nommer aux offices dont on est « nommeur »", "offices"),
    ("personnes.verifier", "Vérifier un statut clérical ou consacré", "offices"),
    ("annonces.publier", "Publier annonces et articles", "paroisse"),
    ("evenements.gerer", "Événements et inscriptions", "paroisse"),
    ("actes.traiter", "Traiter les demandes d'actes", "actes"),
    ("actes.superviser", "Indicateurs agrégés des demandes d'actes", "actes"),
    ("messagerie.recevoir_fideles", "Être joignable par les fidèles", "messagerie"),
    ("confessions.gerer", "Gérer ses créneaux de confession", "confessions"),
    ("confessions.voir_planning", "Voir le planning des confessions (initiales)", "confessions"),
    ("tableau_bord.voir", "Tableau de bord du nœud", "pilotage"),
    ("audit.voir", "Journal d'audit du nœud", "pilotage"),
    ("plateforme.admin", "Administration Numerisen (hors arbre)", "plateforme"),
]

# (code, libellé, types de nœuds, ordre requis, cardinalité, nommé par, nommé par la plateforme,
#  hérite, capacités)
OFFICES = [
    (
        "eveque_diocesain",
        "Évêque diocésain",
        ["diocese"],
        "eveque",
        "one",
        [],
        True,
        True,
        [
            "structure.gerer",
            "horaires.gerer",
            "offices.nommer",
            "personnes.verifier",
            "annonces.publier",
            "evenements.gerer",
            "actes.traiter",
            "actes.superviser",
            "confessions.gerer",
            "confessions.voir_planning",
            "tableau_bord.voir",
            "audit.voir",
        ],
    ),
    (
        "eveque_auxiliaire",
        "Évêque auxiliaire",
        ["diocese"],
        "eveque",
        "many",
        [],
        True,
        True,
        ["tableau_bord.voir", "actes.superviser", "annonces.publier", "audit.voir"],
    ),
    (
        "vicaire_general",
        "Vicaire général / épiscopal",
        ["diocese", "zone"],
        "pretre",
        "many",
        ["eveque_diocesain"],
        False,
        True,
        ["structure.gerer", "offices.nommer", "tableau_bord.voir", "actes.superviser", "audit.voir"],
    ),
    (
        "chancelier",
        "Chancelier",
        ["diocese"],
        "aucun",
        "one",
        ["eveque_diocesain"],
        False,
        True,
        ["structure.gerer", "offices.nommer", "personnes.verifier", "tableau_bord.voir", "audit.voir"],
    ),
    (
        "delegue_numerique_diocesain",
        "Délégué diocésain au numérique",
        ["diocese"],
        "aucun",
        "many",
        ["eveque_diocesain", "chancelier"],
        False,
        True,
        ["structure.gerer", "horaires.gerer", "tableau_bord.voir"],
    ),
    (
        "econome_diocesain",
        "Économe diocésain",
        ["diocese"],
        "aucun",
        "one",
        ["eveque_diocesain"],
        False,
        True,
        ["tableau_bord.voir"],
    ),
    (
        "doyen",
        "Doyen",
        ["doyenne"],
        "pretre",
        "one",
        ["eveque_diocesain", "chancelier"],
        False,
        True,
        ["tableau_bord.voir", "actes.superviser"],
    ),
    (
        "cure",
        "Curé / administrateur paroissial",
        ["paroisse", "quasi_paroisse"],
        "pretre",
        "one",
        ["eveque_diocesain", "chancelier"],
        False,
        True,
        [
            "horaires.gerer",
            "offices.nommer",
            "annonces.publier",
            "evenements.gerer",
            "actes.traiter",
            "messagerie.recevoir_fideles",
            "confessions.gerer",
            "confessions.voir_planning",
            "tableau_bord.voir",
            "audit.voir",
        ],
    ),
    (
        "cure_in_solidum",
        "Curé in solidum",
        ["paroisse", "quasi_paroisse"],
        "pretre",
        "many",
        ["eveque_diocesain", "chancelier"],
        False,
        True,
        [
            "horaires.gerer",
            "offices.nommer",
            "annonces.publier",
            "evenements.gerer",
            "actes.traiter",
            "messagerie.recevoir_fideles",
            "confessions.gerer",
            "confessions.voir_planning",
            "tableau_bord.voir",
            "audit.voir",
        ],
    ),
    (
        "vicaire_paroissial",
        "Vicaire paroissial",
        ["paroisse", "quasi_paroisse"],
        "pretre",
        "many",
        ["eveque_diocesain", "chancelier"],
        False,
        True,
        ["annonces.publier", "evenements.gerer", "actes.traiter", "messagerie.recevoir_fideles", "confessions.gerer"],
    ),
    (
        "aumonier",
        "Aumônier",
        ["aumonerie"],
        "pretre",
        "one",
        ["eveque_diocesain"],
        False,
        False,
        ["annonces.publier", "evenements.gerer", "messagerie.recevoir_fideles", "confessions.gerer"],
    ),
    (
        "recteur",
        "Recteur de sanctuaire / d'église",
        ["paroisse", "quasi_paroisse", "aumonerie"],
        "pretre",
        "one",
        ["eveque_diocesain"],
        False,
        False,
        ["horaires.gerer", "annonces.publier", "confessions.gerer"],
    ),
    (
        "secretaire_paroissial",
        "Secrétaire paroissial",
        ["paroisse", "quasi_paroisse"],
        "aucun",
        "many",
        ["cure", "cure_in_solidum"],
        False,
        True,
        [
            "horaires.gerer",
            "annonces.publier",
            "evenements.gerer",
            "actes.traiter",
            "confessions.voir_planning",
            "tableau_bord.voir",
        ],
    ),
    (
        "referent_numerique",
        "Référent numérique paroissial",
        ["paroisse", "quasi_paroisse"],
        "aucun",
        "many",
        ["cure", "cure_in_solidum"],
        False,
        True,
        ["horaires.gerer", "annonces.publier", "evenements.gerer", "tableau_bord.voir"],
    ),
    (
        "catechiste",
        "Catéchiste",
        ["paroisse", "quasi_paroisse", "ceb"],
        "aucun",
        "many",
        ["cure", "cure_in_solidum"],
        False,
        False,
        ["evenements.gerer"],
    ),
    (
        "responsable_ceb",
        "Responsable de CEB",
        ["ceb"],
        "aucun",
        "many",
        ["cure", "cure_in_solidum"],
        False,
        False,
        ["annonces.publier", "evenements.gerer"],
    ),
]


def seed(apps, schema_editor):
    Capability = apps.get_model("hierarchy", "Capability")
    OfficeType = apps.get_model("hierarchy", "OfficeType")
    NodeType = apps.get_model("hierarchy", "NodeType")

    capabilities = {}
    for code, label, domain in CAPABILITIES:
        capabilities[code], _ = Capability.objects.get_or_create(code=code, defaults={"label": label, "domain": domain})
    node_types = {t.code: t for t in NodeType.objects.all()}
    offices = {}
    for code, label, types, order, cardinality, _by, by_platform, inherits, caps in OFFICES:
        office, created = OfficeType.objects.get_or_create(
            code=code,
            defaults={
                "label": label,
                "required_order": order,
                "cardinality": cardinality,
                "appointed_by_platform": by_platform,
                "inherits_down": inherits,
                "is_system": True,
            },
        )
        offices[code] = office
        if created:
            office.node_types.add(*[node_types[t] for t in types if t in node_types])
            office.capabilities.add(*[capabilities[c] for c in caps])
    for code, _label, _types, _order, _cardinality, by, *_rest in OFFICES:
        if not offices[code].appointed_by.exists():
            offices[code].appointed_by.add(*[offices[b] for b in by])


def unseed(apps, schema_editor):
    OfficeType = apps.get_model("hierarchy", "OfficeType")
    Capability = apps.get_model("hierarchy", "Capability")
    OfficeType.objects.filter(code__in=[o[0] for o in OFFICES], assignments__isnull=True).delete()
    Capability.objects.filter(
        code__in=[c[0] for c in CAPABILITIES], office_types__isnull=True, overrides__isnull=True
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("hierarchy", "0003_seed_node_types")]

    operations = [migrations.RunPython(seed, unseed)]
