"""La Parole (SRS §3.4, ADR-008)."""

from django.core.exceptions import ImproperlyConfigured

from config.env import env

# Source des lectures du jour :
# - "crampon_refs" (défaut) : références du jour, texte tiré de la Bible locale (BIBLE_EDITION) ;
# - "aelf" : texte AELF, UNIQUEMENT avec un accord écrit de l'AELF.
LITURGY_SOURCE = env("LITURGY_SOURCE", default="crampon_refs")
if LITURGY_SOURCE not in ("aelf", "crampon_refs"):
    raise ImproperlyConfigured("LITURGY_SOURCE doit valoir 'aelf' ou 'crampon_refs'.")
LITURGY_ZONE = env("LITURGY_ZONE", default="afrique")

# Édition biblique servie (valeur de Verse.source_file). Vide : toutes les éditions en base
# (comportement historique, à ne garder que le temps d'importer la Crampon).
BIBLE_EDITION = env("BIBLE_EDITION", default="")
BIBLE_EDITIONS = {
    "crampon1923": "Bible Crampon (1923), domaine public",
    "aelf": "Traduction liturgique AELF",
}

# Calendrier liturgique : usages à confirmer par la Conférence épiscopale.
LITURGY_EPIPHANY_ON_SUNDAY = env.bool("LITURGY_EPIPHANY_ON_SUNDAY", default=True)
LITURGY_ASCENSION_ON_SUNDAY = env.bool("LITURGY_ASCENSION_ON_SUNDAY", default=False)
LITURGY_CORPUS_CHRISTI_ON_SUNDAY = env.bool("LITURGY_CORPUS_CHRISTI_ON_SUNDAY", default=True)

if LITURGY_SOURCE == "crampon_refs" and not BIBLE_EDITION:
    import logging

    logging.getLogger(__name__).warning(
        "BIBLE_EDITION vide en mode crampon_refs : toutes les éditions en base sont servies, "
        "y compris un texte AELF importé. Positionner BIBLE_EDITION=crampon1923 après l'import (ADR-008)."
    )

# Recherche et proximité des versets : plein texte PostgreSQL, sans IA ni modèle (ADR-018).
# `fr_unaccent` (français, sans accents, racinisé) sert à la fois à remplir `tsv` et à interroger.
PG_TS_CONFIG = "fr_unaccent"

# « Pour vous aujourd'hui » : recommandations de versets et de livres (plan V2 §6), par proximité
# lexicale pondérée par la rareté des mots (TF-IDF, apps/bible/services/recommendation_service.py).
# Poids des signaux décroissant de moitié tous les PAROLE_RECO_HALF_LIFE_DAYS jours ;
# on ne regarde pas au-delà de PAROLE_RECO_HISTORY_DAYS.
PAROLE_RECO_HALF_LIFE_DAYS = env.int("PAROLE_RECO_HALF_LIFE_DAYS", default=30)
PAROLE_RECO_HISTORY_DAYS = env.int("PAROLE_RECO_HISTORY_DAYS", default=90)
# Un verset lu (ou un chapitre lu) depuis moins de N jours n'est pas reproposé.
PAROLE_RECO_EXCLUDE_READ_DAYS = env.int("PAROLE_RECO_EXCLUDE_READ_DAYS", default=60)
# Précalcul nocturne : seulement les fidèles qui ont lu ou marqué un verset depuis N jours.
PAROLE_RECO_ACTIVE_DAYS = env.int("PAROLE_RECO_ACTIVE_DAYS", default=30)
# Versets les plus proches du profil retenus avant filtrage et diversification.
PAROLE_RECO_CANDIDATES = env.int("PAROLE_RECO_CANDIDATES", default=200)
# Bonus (sans unité, ajouté à la proximité normalisée, 1 = le verset le plus proche) : proximité avec
# l'évangile du jour,
# verset faisant partie des lectures du jour, livre de saison (Avent, Carême…).
PAROLE_RECO_LITURGY_BONUS = env.float("PAROLE_RECO_LITURGY_BONUS", default=0.15)
PAROLE_RECO_READING_BONUS = env.float("PAROLE_RECO_READING_BONUS", default=0.10)
PAROLE_RECO_SEASON_BONUS = env.float("PAROLE_RECO_SEASON_BONUS", default=0.05)
# Au-delà de cette proximité normalisée avec l'évangile du jour, on l'explique (« En lien avec l'évangile du jour »).
PAROLE_RECO_LITURGY_REASON_MIN = env.float("PAROLE_RECO_LITURGY_REASON_MIN", default=0.6)
# Recommandations précalculées conservées N jours (purge par la tâche nocturne).
PAROLE_RECO_RETENTION_DAYS = env.int("PAROLE_RECO_RETENTION_DAYS", default=7)
