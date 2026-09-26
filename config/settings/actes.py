"""Demandes d'actes (SRS §3.6)."""

from config.env import env

# Durée de validité (secondes) d'un lien de consultation d'une pièce jointe du fidèle.
# Court : le lien est signé pour UNE personne et UNE pièce, mais il circule dans une URL.
DOCUMENTS_ATTACHMENT_URL_TTL = env.int("DOCUMENTS_ATTACHMENT_URL_TTL", default=300)

# Délai indicatif (jours) annoncé au fidèle quand ni sa paroisse ni un nœud parent n'en
# ont réglé un (DocumentSlaSetting.indicative_days). Indicatif seulement : jamais un engagement.
DOCUMENTS_DEFAULT_INDICATIVE_DAYS = env.int("DOCUMENTS_DEFAULT_INDICATIVE_DAYS", default=7)
