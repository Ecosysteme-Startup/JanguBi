"""Profils de paramétrage de la hiérarchie (données, aucune logique).

Le profil « senegal » charge les types de nœuds, la Province de Dakar, les
7 diocèses, les 5 doyennés de l'archidiocèse de Dakar et la paroisse pilote
Saint-Dominique (SRS EF-HIE-07).
"""

from datetime import time
from typing import NotRequired, TypedDict


class NodeTypeSpec(TypedDict):
    code: str
    label: str
    is_territorial: bool
    holds_registers: bool
    order: int
    parents: list[str]


class NodeSpec(TypedDict, total=False):
    code: str
    type: str
    name: str
    parent: str | None
    city: str
    is_active_on_platform: bool


class PlaceSpec(TypedDict):
    node: str
    name: str
    kind: str
    is_main: bool
    city: str


class ScheduleSpec(TypedDict, total=False):
    place: str
    kind: str
    weekdays: list[int]
    start_time: time
    end_time: time | None


# Types de nœuds (HIERARCHIE-ECCLESIALE-PARAMETRAGE.md §1.2 ; SRS EF-HIE-09).
SENEGAL_NODE_TYPES: list[NodeTypeSpec] = [
    {"code": "province", "label": "Province ecclésiastique", "is_territorial": True, "holds_registers": False, "order": 10, "parents": []},
    {"code": "diocese", "label": "Diocèse", "is_territorial": True, "holds_registers": False, "order": 20, "parents": ["province"]},
    {"code": "zone", "label": "Zone pastorale", "is_territorial": True, "holds_registers": False, "order": 30, "parents": ["diocese"]},
    {"code": "doyenne", "label": "Doyenné", "is_territorial": True, "holds_registers": False, "order": 40, "parents": ["diocese", "zone"]},
    {"code": "paroisse", "label": "Paroisse", "is_territorial": True, "holds_registers": True, "order": 50, "parents": ["doyenne", "zone", "diocese"]},
    {"code": "quasi_paroisse", "label": "Quasi-paroisse / secteur pastoral", "is_territorial": True, "holds_registers": True, "order": 55, "parents": ["doyenne", "zone", "diocese"]},
    {"code": "aumonerie", "label": "Aumônerie", "is_territorial": False, "holds_registers": False, "order": 60, "parents": ["diocese", "zone"]},
    {"code": "ceb", "label": "Communauté ecclésiale de base", "is_territorial": True, "holds_registers": False, "order": 70, "parents": ["paroisse", "quasi_paroisse"]},
    {"code": "mouvement", "label": "Mouvement / association", "is_territorial": False, "holds_registers": False, "order": 80, "parents": ["paroisse", "quasi_paroisse", "diocese"]},
    {"code": "institut", "label": "Institut de vie consacrée", "is_territorial": False, "holds_registers": False, "order": 100, "parents": []},
    {"code": "province_religieuse", "label": "Province religieuse", "is_territorial": False, "holds_registers": False, "order": 110, "parents": ["institut"]},
    {"code": "communaute", "label": "Communauté religieuse", "is_territorial": False, "holds_registers": False, "order": 120, "parents": ["institut", "province_religieuse"]},
]

PILOT_PARISH_CODE = "DAK-SAINT-DOMINIQUE"

# Au Sénégal, une seule province ecclésiastique (Dakar) regroupe les 7 diocèses.
SENEGAL_NODES: list[NodeSpec] = [
    {"code": "DAKP", "type": "province", "name": "Province ecclésiastique de Dakar", "parent": None},
    {"code": "DAK", "type": "diocese", "name": "Archidiocèse de Dakar", "parent": "DAKP", "city": "Dakar"},
    {"code": "THI", "type": "diocese", "name": "Diocèse de Thiès", "parent": "DAKP", "city": "Thiès"},
    {"code": "KAO", "type": "diocese", "name": "Diocèse de Kaolack", "parent": "DAKP", "city": "Kaolack"},
    {"code": "SLO", "type": "diocese", "name": "Diocèse de Saint-Louis du Sénégal", "parent": "DAKP", "city": "Saint-Louis"},
    {"code": "ZIG", "type": "diocese", "name": "Diocèse de Ziguinchor", "parent": "DAKP", "city": "Ziguinchor"},
    {"code": "KOL", "type": "diocese", "name": "Diocèse de Kolda", "parent": "DAKP", "city": "Kolda"},
    {"code": "TAM", "type": "diocese", "name": "Diocèse de Tambacounda", "parent": "DAKP", "city": "Tambacounda"},
    {"code": "DAK-D-PLATEAU-MEDINA", "type": "doyenne", "name": "Doyenné Plateau-Médina", "parent": "DAK", "city": "Dakar"},
    {"code": "DAK-D-GRAND-DAKAR-YOFF", "type": "doyenne", "name": "Doyenné Grand Dakar-Yoff", "parent": "DAK", "city": "Dakar"},
    {"code": "DAK-D-NIAYES", "type": "doyenne", "name": "Doyenné des Niayes", "parent": "DAK"},
    {"code": "DAK-D-SINE", "type": "doyenne", "name": "Doyenné du Sine", "parent": "DAK"},
    {"code": "DAK-D-PETITE-COTE", "type": "doyenne", "name": "Doyenné de la Petite-Côte", "parent": "DAK"},
    # Rattachée directement à l'archidiocèse : le doyenné est à confirmer par la chancellerie.
    {
        "code": PILOT_PARISH_CODE,
        "type": "paroisse",
        "name": "Paroisse Saint-Dominique",
        "parent": "DAK",
        "city": "Dakar",
        "is_active_on_platform": True,
    },
]

SENEGAL_PLACES: list[PlaceSpec] = [
    {"node": PILOT_PARISH_CODE, "name": "Église Saint-Dominique", "kind": "eglise_paroissiale", "is_main": True, "city": "Dakar"},
    {"node": PILOT_PARISH_CODE, "name": "Chapelle de la Cité universitaire", "kind": "chapelle", "is_main": False, "city": "Dakar"},
]

_WEEKDAYS = [0, 1, 2, 3, 4]  # lundi → vendredi

# Horaires du pilote (brief) : dimanche 7h30, 9h30, 11h30, 18h30 ; semaine 7h et 18h30 ;
# samedi confessions de 16h à 18h. Portés par l'église paroissiale.
SENEGAL_SCHEDULES: list[ScheduleSpec] = [
    {"place": "Église Saint-Dominique", "kind": "messe", "weekdays": [6], "start_time": time(7, 30)},
    {"place": "Église Saint-Dominique", "kind": "messe", "weekdays": [6], "start_time": time(9, 30)},
    {"place": "Église Saint-Dominique", "kind": "messe", "weekdays": [6], "start_time": time(11, 30)},
    {"place": "Église Saint-Dominique", "kind": "messe", "weekdays": [6], "start_time": time(18, 30)},
    {"place": "Église Saint-Dominique", "kind": "messe", "weekdays": _WEEKDAYS, "start_time": time(7, 0)},
    {"place": "Église Saint-Dominique", "kind": "messe", "weekdays": _WEEKDAYS, "start_time": time(18, 30)},
    {
        "place": "Église Saint-Dominique",
        "kind": "confession",
        "weekdays": [5],
        "start_time": time(16, 0),
        "end_time": time(18, 0),
    },
]

class Profile(TypedDict):
    node_types: list[NodeTypeSpec]
    nodes: list[NodeSpec]
    places: list[PlaceSpec]
    schedules: list[ScheduleSpec]


PROFILES: dict[str, Profile] = {
    "senegal": {
        "node_types": SENEGAL_NODE_TYPES,
        "nodes": SENEGAL_NODES,
        "places": SENEGAL_PLACES,
        "schedules": SENEGAL_SCHEDULES,
    },
}


# --- Capacités et offices (SRS §6.2, §6.3) ------------------------------------------


class CapabilitySpec(TypedDict):
    code: str
    label: str
    domain: str


class QualitySpec(TypedDict):
    code: str
    label: str


# Qualités du titulaire d'une cure : on affiche le titre réel, jamais la double forme (c. 539-540).
CURE_QUALITIES: list[QualitySpec] = [
    {"code": "cure", "label": "Curé"},
    {"code": "administrateur", "label": "Administrateur paroissial"},
]


class OfficeSpec(TypedDict):
    code: str
    label: str
    node_types: list[str]
    required_order: str
    cardinality: str
    appointed_by: list[str]
    appointed_by_platform: bool
    inherits_down: bool
    capabilities: list[str]
    qualities: NotRequired[list[QualitySpec]]


# Catalogue FERMÉ (RG-14) : ajouter une capacité = une décision + un ADR + du code.
CAPABILITIES: list[CapabilitySpec] = [
    {"code": "structure.gerer", "label": "Créer ou modifier les nœuds et lieux de culte du sous-arbre", "domain": "structure"},
    {"code": "horaires.gerer", "label": "Horaires et exceptions des lieux de culte", "domain": "structure"},
    {"code": "offices.nommer", "label": "Nommer aux offices dont on est « nommeur »", "domain": "offices"},
    {"code": "personnes.verifier", "label": "Vérifier un statut clérical ou consacré", "domain": "offices"},
    {"code": "annonces.publier", "label": "Publier annonces et articles", "domain": "paroisse"},
    {"code": "evenements.gerer", "label": "Événements et inscriptions", "domain": "paroisse"},
    {"code": "actes.traiter", "label": "Traiter les demandes d'actes", "domain": "actes"},
    {"code": "actes.superviser", "label": "Indicateurs agrégés des demandes d'actes", "domain": "actes"},
    {"code": "messagerie.recevoir_fideles", "label": "Être joignable par les fidèles", "domain": "messagerie"},
    {"code": "confessions.gerer", "label": "Gérer ses créneaux de confession", "domain": "confessions"},
    {"code": "confessions.voir_planning", "label": "Voir le planning des confessions (initiales)", "domain": "confessions"},
    {"code": "tableau_bord.voir", "label": "Tableau de bord du nœud", "domain": "pilotage"},
    {"code": "audit.voir", "label": "Journal d'audit du nœud", "domain": "pilotage"},
    {"code": "plateforme.admin", "label": "Administration Numerisen (hors arbre)", "domain": "plateforme"},
    # Dons et quêtes (ADR-017). Lecture fine réservée aux nominations sur la paroisse même
    # (apps/donations/access.py) : au-dessus de la paroisse, agrégats seulement.
    {"code": "dons.voir_fonds", "label": "Voir les fonds, la synthèse et les opérations (noms masqués)", "domain": "dons"},
    {"code": "dons.gerer_fonds", "label": "Créer, publier et clore les fonds et campagnes", "domain": "dons"},
    {"code": "dons.saisir_quete", "label": "Saisir et valider les quêtes en espèces", "domain": "dons"},
    {"code": "dons.voir_donateurs", "label": "Voir le nom des donateurs non anonymes", "domain": "dons"},
    {"code": "dons.exporter", "label": "Export comptable et rapprochement", "domain": "dons"},
    {"code": "dons.definir_quete_imperee", "label": "Définir une quête impérée et suivre ses agrégats", "domain": "dons"},
    # Sonothèque paroissiale (plan suite V2, §5) : publier les enregistrements de la paroisse, de
    # la chorale ou du mouvement ; modérer (signalements, retrait) sur le sous-arbre.
    {"code": "audio.publier", "label": "Publier des enregistrements dans la sonothèque", "domain": "audio"},
    {"code": "audio.moderer", "label": "Modérer la sonothèque (signalements, retrait)", "domain": "audio"},
    # V2 : agrégats au-dessus de la paroisse (arrondis au millier, aucun nom, ordre alphabétique).
    {"code": "dons.voir_agregats", "label": "Voir les agrégats des dons des paroisses (arrondis, sans nom)", "domain": "dons"},
    # V2, décisions 6-8 (29/09/2026) : adhésion libre, mais la paroisse peut retirer un membre.
    # Donnée personnelle : réservée à la paroisse même (pas à l'évêque, RG-11).
    {"code": "paroissiens.gerer", "label": "Voir les membres de la paroisse et en retirer", "domain": "paroisse"},
    # Lot V1-routes : invitations et validation des comptes du clergé (diocèse, plateforme).
    {"code": "comptes.valider", "label": "Inviter, valider et activer les comptes du clergé", "domain": "offices"},
    # Lot V1-routes : intentions de messe reçues par le secrétariat (aucun montant, aucun paiement).
    {"code": "intentions.gerer", "label": "Recevoir et planifier les intentions de messe", "domain": "paroisse"},
    # Administration des comptes (docs/ADMIN-KEYCLOAK.md) : créer, modifier, désactiver les comptes
    # de son périmètre, jamais ceux d'un office qu'on ne pourrait pas nommer. Migration 0015.
    {"code": "comptes.gerer", "label": "Créer et gérer les comptes de son périmètre", "domain": "offices"},
]

# Capacités « dons » par office (ADR-017). Séparées pour que la migration de données
# puisse les ajouter aux offices déjà chargés (le chargeur ne complète pas un office existant).
DONS_PAROISSE_CAPABILITIES = [
    "dons.voir_fonds",
    "dons.gerer_fonds",
    "dons.saisir_quete",
    "dons.voir_donateurs",
    "dons.exporter",
]
DONS_OFFICE_CAPABILITIES: dict[str, list[str]] = {
    "cure": DONS_PAROISSE_CAPABILITIES,
    "cure_in_solidum": DONS_PAROISSE_CAPABILITIES,
    "econome_paroissial": DONS_PAROISSE_CAPABILITIES,
    "secretaire_paroissial": ["dons.voir_fonds", "dons.saisir_quete"],
    "eveque_diocesain": ["dons.definir_quete_imperee", "dons.voir_agregats"],
    "econome_diocesain": ["dons.definir_quete_imperee", "dons.voir_agregats"],
}

# Capacités « audio » par office (sonothèque, plan suite V2 §5). Même raison que pour les dons :
# la migration 0010 les ajoute aux offices déjà chargés.
AUDIO_OFFICE_CAPABILITIES: dict[str, list[str]] = {
    "cure": ["audio.publier", "audio.moderer"],
    "cure_in_solidum": ["audio.publier", "audio.moderer"],
    "vicaire_paroissial": ["audio.publier"],
    "secretaire_paroissial": ["audio.publier"],
    "referent_numerique": ["audio.publier"],
    "aumonier": ["audio.publier"],
    "delegue_numerique_diocesain": ["audio.publier", "audio.moderer"],
}

# Lot V1-routes : la migration 0014 ajoute ces capacités aux offices déjà chargés.
V1_ROUTES_OFFICE_CAPABILITIES: dict[str, list[str]] = {
    "chancelier": ["comptes.valider"],
    "vicaire_general": ["comptes.valider"],
    "eveque_diocesain": ["comptes.valider", "intentions.gerer"],
    "cure": ["intentions.gerer"],
    "cure_in_solidum": ["intentions.gerer"],
    "secretaire_paroissial": ["intentions.gerer"],
}

# Membres de la paroisse (décisions 6-8) : la migration 0013 l'ajoute aux offices déjà chargés.
MEMBRES_OFFICE_CAPABILITIES: dict[str, list[str]] = {
    "cure": ["paroissiens.gerer"],
    "cure_in_solidum": ["paroissiens.gerer"],
    "secretaire_paroissial": ["paroissiens.gerer"],
}

# L'évêque n'a des dons que la définition des quêtes impérées (ADR-017) : ni les noms des
# donateurs ni la gestion des fonds paroissiaux.
_ALL_BUT_PLATFORM_AND_MESSAGING = [
    c["code"]
    for c in CAPABILITIES
    if c["code"] not in {"plateforme.admin", "messagerie.recevoir_fideles", "paroissiens.gerer"}
    and c["domain"] != "dons"
] + ["dons.definir_quete_imperee", "dons.voir_agregats"]
_CURE_CAPABILITIES = [
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
    *DONS_PAROISSE_CAPABILITIES,
    *AUDIO_OFFICE_CAPABILITIES["cure"],
    *MEMBRES_OFFICE_CAPABILITIES["cure"],
    "intentions.gerer",
    "comptes.gerer",
]

OFFICES: list[OfficeSpec] = [
    {"code": "eveque_diocesain", "label": "Évêque diocésain", "node_types": ["diocese"], "required_order": "eveque", "cardinality": "one", "appointed_by": [], "appointed_by_platform": True, "inherits_down": True, "capabilities": _ALL_BUT_PLATFORM_AND_MESSAGING},
    {"code": "eveque_auxiliaire", "label": "Évêque auxiliaire", "node_types": ["diocese"], "required_order": "eveque", "cardinality": "many", "appointed_by": [], "appointed_by_platform": True, "inherits_down": True, "capabilities": ["tableau_bord.voir", "actes.superviser", "annonces.publier", "audit.voir"]},
    {"code": "vicaire_general", "label": "Vicaire général / épiscopal", "node_types": ["diocese", "zone"], "required_order": "pretre", "cardinality": "many", "appointed_by": ["eveque_diocesain"], "appointed_by_platform": False, "inherits_down": True, "capabilities": ["structure.gerer", "offices.nommer", "tableau_bord.voir", "actes.superviser", "audit.voir", "comptes.valider", "comptes.gerer"]},
    {"code": "chancelier", "label": "Chancelier", "node_types": ["diocese"], "required_order": "aucun", "cardinality": "one", "appointed_by": ["eveque_diocesain"], "appointed_by_platform": False, "inherits_down": True, "capabilities": ["structure.gerer", "offices.nommer", "personnes.verifier", "tableau_bord.voir", "audit.voir", "comptes.valider", "comptes.gerer"]},
    {"code": "delegue_numerique_diocesain", "label": "Délégué diocésain au numérique", "node_types": ["diocese"], "required_order": "aucun", "cardinality": "many", "appointed_by": ["eveque_diocesain", "chancelier"], "appointed_by_platform": False, "inherits_down": True, "capabilities": ["structure.gerer", "horaires.gerer", "tableau_bord.voir", "audio.publier", "audio.moderer"]},
    {"code": "econome_diocesain", "label": "Économe diocésain", "node_types": ["diocese"], "required_order": "aucun", "cardinality": "one", "appointed_by": ["eveque_diocesain"], "appointed_by_platform": False, "inherits_down": True, "capabilities": ["tableau_bord.voir", "dons.definir_quete_imperee", "dons.voir_agregats"]},
    {"code": "doyen", "label": "Doyen", "node_types": ["doyenne"], "required_order": "pretre", "cardinality": "one", "appointed_by": ["eveque_diocesain", "chancelier"], "appointed_by_platform": False, "inherits_down": True, "capabilities": ["tableau_bord.voir", "actes.superviser"]},
    {"code": "cure", "label": "Curé / administrateur paroissial", "node_types": ["paroisse", "quasi_paroisse"], "required_order": "pretre", "cardinality": "one", "appointed_by": ["eveque_diocesain", "chancelier"], "appointed_by_platform": False, "inherits_down": True, "capabilities": _CURE_CAPABILITIES, "qualities": CURE_QUALITIES},
    # Curés « in solidum » (c. 517) : l'exception à la cardinalité du curé (EF-PER-05).
    {"code": "cure_in_solidum", "label": "Curé in solidum", "node_types": ["paroisse", "quasi_paroisse"], "required_order": "pretre", "cardinality": "many", "appointed_by": ["eveque_diocesain", "chancelier"], "appointed_by_platform": False, "inherits_down": True, "capabilities": _CURE_CAPABILITIES},
    {"code": "vicaire_paroissial", "label": "Vicaire paroissial", "node_types": ["paroisse", "quasi_paroisse"], "required_order": "pretre", "cardinality": "many", "appointed_by": ["eveque_diocesain", "chancelier"], "appointed_by_platform": False, "inherits_down": True, "capabilities": ["annonces.publier", "evenements.gerer", "actes.traiter", "messagerie.recevoir_fideles", "confessions.gerer", "audio.publier"]},
    {"code": "aumonier", "label": "Aumônier", "node_types": ["aumonerie"], "required_order": "pretre", "cardinality": "one", "appointed_by": ["eveque_diocesain"], "appointed_by_platform": False, "inherits_down": False, "capabilities": ["annonces.publier", "evenements.gerer", "messagerie.recevoir_fideles", "confessions.gerer", "audio.publier"]},
    {"code": "recteur", "label": "Recteur de sanctuaire / d'église", "node_types": ["paroisse", "quasi_paroisse", "aumonerie"], "required_order": "pretre", "cardinality": "one", "appointed_by": ["eveque_diocesain"], "appointed_by_platform": False, "inherits_down": False, "capabilities": ["horaires.gerer", "annonces.publier", "confessions.gerer"]},
    {"code": "secretaire_paroissial", "label": "Secrétaire paroissial", "node_types": ["paroisse", "quasi_paroisse"], "required_order": "aucun", "cardinality": "many", "appointed_by": ["cure", "cure_in_solidum"], "appointed_by_platform": False, "inherits_down": True, "capabilities": ["horaires.gerer", "annonces.publier", "evenements.gerer", "actes.traiter", "confessions.voir_planning", "tableau_bord.voir", "dons.voir_fonds", "dons.saisir_quete", "audio.publier", "paroissiens.gerer", "intentions.gerer"]},
    {"code": "econome_paroissial", "label": "Économe paroissial", "node_types": ["paroisse", "quasi_paroisse"], "required_order": "aucun", "cardinality": "one", "appointed_by": ["cure", "cure_in_solidum"], "appointed_by_platform": False, "inherits_down": True, "capabilities": ["tableau_bord.voir", *DONS_PAROISSE_CAPABILITIES]},
    {"code": "referent_numerique", "label": "Référent numérique paroissial", "node_types": ["paroisse", "quasi_paroisse"], "required_order": "aucun", "cardinality": "many", "appointed_by": ["cure", "cure_in_solidum"], "appointed_by_platform": False, "inherits_down": True, "capabilities": ["horaires.gerer", "annonces.publier", "evenements.gerer", "tableau_bord.voir", "audio.publier"]},
    {"code": "catechiste", "label": "Catéchiste", "node_types": ["paroisse", "quasi_paroisse", "ceb"], "required_order": "aucun", "cardinality": "many", "appointed_by": ["cure", "cure_in_solidum"], "appointed_by_platform": False, "inherits_down": False, "capabilities": ["evenements.gerer"]},
    {"code": "responsable_ceb", "label": "Responsable de CEB", "node_types": ["ceb"], "required_order": "aucun", "cardinality": "many", "appointed_by": ["cure", "cure_in_solidum"], "appointed_by_platform": False, "inherits_down": False, "capabilities": ["annonces.publier", "evenements.gerer"]},
]

# Capacités de l'administrateur plateforme (Numerisen), valables sur tout l'arbre.
# Délibérément SANS actes.traiter, messagerie.* ni confessions.* : la plateforme
# administre le référentiel, elle ne traite pas les dossiers des paroisses (RG-09).
PLATFORM_ADMIN_CAPABILITIES = frozenset(
    {
        "plateforme.admin",
        "structure.gerer",
        "horaires.gerer",
        "offices.nommer",
        "personnes.verifier",
        "tableau_bord.voir",
        "actes.superviser",
        "audit.voir",
        # Sonothèque : la plateforme peut retirer un contenu signalé (droits d'auteur, contenu
        # inapproprié) partout, sans publier à la place des paroisses.
        "audio.moderer",
        # Lot V1-routes : la plateforme invite et valide les comptes du clergé.
        "comptes.valider",
        # Administration des comptes et synchronisation Keycloak (docs/ADMIN-KEYCLOAK.md).
        "comptes.gerer",
    }
)
