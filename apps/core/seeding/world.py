"""Référentiel fictif du « monde » semé : paroisses supplémentaires, sources audio, lieux."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.core.seeding.context import SeedContext

SEED_PARISH_PREFIX = "SEED-PAR-"

# Paroisses supplémentaires (noms de patronage courants ; quartiers de Dakar et environs).
# (nom, quartier, nom de l'église principale, chapelles)
EXTRA_PARISHES: list[tuple[str, str, list[str]]] = [
    ("Paroisse Saint-Joseph de Médina", "Médina", ["Chapelle Saint-Charles-Lwanga"]),
    ("Paroisse Notre-Dame des Anges", "Ouakam", ["Chapelle Sainte-Bernadette"]),
    ("Paroisse Saint-Pierre des Baobabs", "Sacré-Cœur", []),
    ("Paroisse Sainte-Anne", "Grand-Yoff", ["Chapelle Saint-Jean-Bosco"]),
    ("Paroisse Saint-Paul", "Grand-Yoff", []),
    ("Paroisse Marie-Immaculée", "Parcelles Assainies", ["Chapelle de l'Unité 15", "Chapelle de l'Unité 22"]),
    ("Paroisse Sainte-Jeanne-d'Arc", "Fann", []),
    ("Paroisse Saint-Augustin", "Pikine", ["Chapelle Sainte-Monique"]),
    ("Paroisse Saint-Michel", "Thiaroye", []),
    ("Paroisse Notre-Dame de Lourdes", "Guédiawaye", ["Chapelle Saint-Martin"]),
    ("Paroisse Sainte-Bernadette", "Rufisque", []),
    ("Paroisse Saint-Charles-Lwanga", "Keur Massar", ["Chapelle Saint-Kizito"]),
    ("Paroisse Saint-Antoine de Padoue", "Yoff", []),
    ("Paroisse Sainte-Marie de la Médina", "Colobane", []),
    ("Paroisse Saint-Jean-Baptiste", "Mermoz", ["Chapelle Saint-Luc"]),
    ("Paroisse Notre-Dame du Cap-Vert", "Hann", []),
    ("Paroisse Saint-François-Xavier", "Liberté 6", []),
    ("Paroisse Sainte-Rita", "Mbao", ["Chapelle Saint-Benoît"]),
    ("Paroisse Saint-Jacques", "Bargny", []),
    ("Paroisse Sainte-Thérèse-de-l'Enfant-Jésus", "Dalifort", []),
    ("Paroisse Saint-Étienne", "Yeumbeul", []),
    ("Paroisse Sainte-Famille", "HLM", ["Chapelle Saint-Dominique-Savio"]),
    ("Paroisse Saint-Luc", "Diamniadio", []),
    ("Paroisse Christ-Roi", "Pikine Est", ["Chapelle Saint-Gabriel"]),
    ("Paroisse Saint-Esprit", "Camberène", []),
    ("Paroisse Saint-Laurent", "Sangalkam", []),
    ("Paroisse Notre-Dame de la Paix", "Keur Mbaye Fall", []),
    ("Paroisse Saint-Vincent-de-Paul", "Niary Tally", []),
    ("Paroisse Saint-Philippe", "Ngor", []),
    ("Paroisse Sainte-Claire", "Point E", []),
    ("Paroisse Saint-Martin-de-Porrès", "Malika", []),
    ("Paroisse Saint-Kizito", "Tivaouane Peulh", []),
    ("Paroisse Sainte-Monique", "Bel-Air", []),
    ("Paroisse Saint-Benoît", "Sébikotane", []),
    ("Paroisse Notre-Dame de Fatima", "Yarakh", []),
    ("Paroisse Saint-Mathieu", "Mamelles", []),
    ("Paroisse Sainte-Agnès", "Cambérène 2", []),
    ("Paroisse Saint-Marc", "Golf Sud", []),
]


def parish_codes(ctx: SeedContext) -> list[str]:
    from apps.core.management.commands.seed_demo import SECOND_PARISH_CODE
    from apps.hierarchy.profiles import PILOT_PARISH_CODE

    extra = max(0, ctx.scale.paroisses - 2)
    return [PILOT_PARISH_CODE, SECOND_PARISH_CODE] + [f"{SEED_PARISH_PREFIX}{i + 1:02d}" for i in range(extra)]


# Sources audio : (type, nom, présentation). Les paroisses ajoutent la leur.
CHORALES = [
    ("Chorale Sainte-Cécile", "La chorale de la messe de 11 h 30, polyphonies et chants à Marie."),
    ("Chorale Saint-Joseph de Médina", "Chants de la liturgie dominicale et répertoire marial."),
    ("Chœur Saint-Augustin", "Chœur des jeunes, animations des veillées."),
    ("Chorale Notre-Dame des Anges", "Messe du dimanche matin, grégorien et cantiques."),
    ("Chorale Sainte-Anne", "Chants de louange et répertoire traditionnel."),
    ("Chœur Marie-Immaculée", "Polyphonie sacrée, concerts de Noël et de Pâques."),
]
MOUVEMENTS = [
    ("Renouveau charismatique", "Enseignements et temps de louange."),
    ("Légion de Marie", "Chapelet médité et prières mariales."),
    ("Jeunesse étudiante catholique", "Récollections et partages de la Parole."),
    ("Mouvement des Focolari", "Méditations sur la Parole de vie."),
]
