"""Dons et quêtes (ADR-017, cadrage DONS-00 §5). Aucun secret en dur."""

from config.env import env

# Agrégateur : "fake" (tests, CI, démonstration) ou "paydunya". production.py refuse "fake".
DONATIONS_PROVIDER = env.str("DONATIONS_PROVIDER", default="fake")
DONATIONS_STORE_NAME = env.str("DONATIONS_STORE_NAME", default="Jàngu Bi")

# Montants en FCFA (entiers). Le KYC reste chez l'agrégateur : ce plafond n'est qu'un garde-fou.
DONATIONS_MIN_AMOUNT = env.int("DONATIONS_MIN_AMOUNT", default=100)
DONATIONS_MAX_AMOUNT = env.int("DONATIONS_MAX_AMOUNT", default=1_000_000)
DONATIONS_SUGGESTED_AMOUNTS = [1000, 2000, 5000, 10000]
# Frais estimés affichés au donateur (points de base : 200 = 2 %), à aligner sur le contrat (H3).
DONATIONS_FEE_RATE_BP = env.int("DONATIONS_FEE_RATE_BP", default=200)

# Délais de la réconciliation.
DONATIONS_PENDING_CHECK_MINUTES = env.int("DONATIONS_PENDING_CHECK_MINUTES", default=15)
DONATIONS_EXPIRE_HOURS = env.int("DONATIONS_EXPIRE_HOURS", default=24)
DONATIONS_DONOR_EMAIL_RETENTION_DAYS = env.int("DONATIONS_DONOR_EMAIL_RETENTION_DAYS", default=90)

# Échéances du bloc « À traiter » (tableaux de bord V2) et clôture mensuelle.
DONATIONS_CASH_VALIDATE_DAYS = env.int("DONATIONS_CASH_VALIDATE_DAYS", default=2)  # quête à confirmer : 48 h
DONATIONS_CASH_DEPOSIT_DAYS = env.int("DONATIONS_CASH_DEPOSIT_DAYS", default=7)  # espèces à déposer
DONATIONS_REMITTANCE_CONFIRM_DAYS = env.int("DONATIONS_REMITTANCE_CONFIRM_DAYS", default=7)  # remise à confirmer
DONATIONS_INCIDENT_DAYS = env.int("DONATIONS_INCIDENT_DAYS", default=7)  # paiement tardif à régulariser
# Jour du mois à partir duquel le mois précédent est clos automatiquement (s'il n'a plus de quête à valider).
DONATIONS_MONTH_CLOSE_DAY = env.int("DONATIONS_MONTH_CLOSE_DAY", default=10)

# URLs du parcours : retour navigateur (lien universel côté front) et notification serveur.
DONATIONS_RETURN_URL = env.str("DONATIONS_RETURN_URL", default="http://localhost:3000/dons/retour")
DONATIONS_CALLBACK_BASE_URL = env.str("DONATIONS_CALLBACK_BASE_URL", default="http://localhost:8001")

# Quota du checkout public, par adresse IP.
DONATIONS_CHECKOUT_THROTTLE_RATE = env.str("DONATIONS_CHECKOUT_THROTTLE_RATE", default="20/hour")

# Chiffrement des payloads de l'agrégateur (vide : dérivée de SECRET_KEY avec un sel propre).
DONATIONS_PAYLOAD_KEY = env.str("DONATIONS_PAYLOAD_KEY", default="")

# Agrégateur factice.
DONATIONS_FAKE_SECRET = env.str("DONATIONS_FAKE_SECRET", default="fake-secret-dev")
DONATIONS_FAKE_CHECKOUT_BASE = env.str("DONATIONS_FAKE_CHECKOUT_BASE", default="https://paiement.exemple.test/checkout")

# PayDunya.
PAYDUNYA_MASTER_KEY = env.str("PAYDUNYA_MASTER_KEY", default="")
PAYDUNYA_PRIVATE_KEY = env.str("PAYDUNYA_PRIVATE_KEY", default="")
PAYDUNYA_TOKEN = env.str("PAYDUNYA_TOKEN", default="")
PAYDUNYA_MODE = env.str("PAYDUNYA_MODE", default="test")
