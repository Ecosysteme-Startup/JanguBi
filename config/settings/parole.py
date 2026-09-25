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
