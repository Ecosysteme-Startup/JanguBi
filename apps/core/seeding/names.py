"""Prénoms chrétiens et noms de famille sénégalais (plan §4) : jamais les noms français de Faker.
Aucun nom réel de clerc en poste n'est visé : les combinaisons sont tirées au hasard."""

from __future__ import annotations

import random
import unicodedata

PRENOMS_F = [
    "Marie", "Anne", "Thérèse", "Bernadette", "Cécile", "Agnès", "Madeleine", "Joséphine", "Hélène", "Claire",
    "Monique", "Rose", "Élisabeth", "Véronique", "Pauline", "Odile", "Christine", "Suzanne", "Albertine",
    "Honorine", "Philomène", "Scholastique", "Colette", "Germaine", "Lucie", "Angèle", "Françoise", "Jeanne",
    "Awa", "Fatou", "Ndèye", "Khady", "Aminata", "Mariama", "Seynabou", "Adji", "Coumba", "Yacine", "Astou",
]  # fmt: skip
PRENOMS_M = [
    "Joseph", "Pierre", "Paul", "Jean", "Jacques", "André", "Michel", "Emmanuel", "Augustin", "Antoine",
    "Louis", "Bernard", "François", "Étienne", "Charles", "Théodore", "Vincent", "Martin", "Benoît",
    "Dominique", "Célestin", "Hyacinthe", "Barthélemy", "Norbert", "Ignace", "Clément", "Léon", "Raphaël",
    "Moussa", "Mamadou", "Ousmane", "Abdou", "Ibrahima", "Modou", "Lamine", "Aliou", "Cheikh", "Pape",
]  # fmt: skip
NOMS = [
    "Diouf", "Faye", "Ndiaye", "Sarr", "Mendy", "Sène", "Diatta", "Coly", "Gomis", "Badji", "Tine", "Sagna",
    "Preira", "Da Silva", "Mané", "Diop", "Ndour", "Thiaw", "Ciss", "Dione", "Faye", "Senghor", "Bassène",
    "Manga", "Sambou", "Tendeng", "Diédhiou", "Mbaye", "Ndong", "Kama", "Mansaly", "Biaye", "Carvalho",
    "Mendes", "Correa", "Lopy", "Sonko", "Goudiaby", "Diémé", "Ndecky", "Basse", "Bakhoum", "Sylva",
]  # fmt: skip


def person(rng: random.Random, sex: str | None = None) -> tuple[str, str, str]:
    """(prénom, nom, sexe « F » ou « M »)."""
    sex = sex or rng.choice("FM")
    first = rng.choice(PRENOMS_F if sex == "F" else PRENOMS_M)
    if rng.random() < 0.18:  # prénom composé
        second = rng.choice(PRENOMS_F if sex == "F" else PRENOMS_M)
        if second != first:
            first = f"{first}-{second}"
    return first, rng.choice(NOMS), sex


def slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "".join(c if c.isalnum() else "-" for c in ascii_text.lower()).strip("-").replace("--", "-")


def phone(n: int) -> str:
    """Plage fictive (plan §2) : +221 70 000 xx xx."""
    n %= 10_000
    return f"+22170000{n:04d}"
