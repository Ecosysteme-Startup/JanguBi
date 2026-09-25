"""Profils de paramétrage de la hiérarchie (données, aucune logique).

Le profil « senegal » charge les types de nœuds, la Province de Dakar, les
7 diocèses, les 5 doyennés de l'archidiocèse de Dakar et la paroisse pilote
Saint-Dominique (SRS EF-HIE-07).
"""

from datetime import time
from typing import TypedDict


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
