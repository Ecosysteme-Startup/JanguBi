"""Énumérations du module Dons et quêtes (ADR-017, cadrage DONS-00 §3)."""

from django.db import models
from django.utils.translation import gettext_lazy as _

# Types de nœuds qui collectent (les dons vont toujours à une paroisse ; H1 : le diocèse encaisse).
PARISH_TYPES: frozenset[str] = frozenset({"paroisse", "quasi_paroisse"})
DIOCESE_TYPES: frozenset[str] = frozenset({"diocese"})
# Nœuds dont on lit les agrégats (``dons.voir_agregats``) : au-dessus de la paroisse.
AGGREGATE_TYPES: frozenset[str] = frozenset({"diocese", "doyenne"})


class FundKind(models.TextChoices):
    """H2. Pas d'offrande de messe : elle relève des intentions de messe (c. 945-958)."""

    QUETE_DOMINICALE = "quete_dominicale", _("Quête dominicale")
    QUETE_IMPEREE = "quete_imperee", _("Quête impérée")
    CAMPAGNE = "campagne", _("Campagne pour un projet")
    CONTRIBUTION_ANNUELLE = "contribution_annuelle", _("Contribution annuelle")


class FundDestination(models.TextChoices):
    PAROISSE = "paroisse", _("Paroisse")
    CURIE = "curie", _("Curie diocésaine")  # quêtes impérées (c. 1266)


class FundStatus(models.TextChoices):
    BROUILLON = "brouillon", _("Brouillon")
    OUVERT = "ouvert", _("Ouvert")
    CLOS = "clos", _("Clos")


class DonationStatus(models.TextChoices):
    INITIE = "initie", _("Initié")
    EN_ATTENTE = "en_attente", _("En attente de confirmation")
    CONFIRME = "confirme", _("Confirmé")
    ECHOUE = "echoue", _("Échoué")
    EXPIRE = "expire", _("Expiré")
    REMBOURSE = "rembourse", _("Remboursé")


# Machine à états stricte (SRS §8.4).
DONATION_TRANSITIONS: dict[str, frozenset[str]] = {
    DonationStatus.INITIE: frozenset({DonationStatus.EN_ATTENTE, DonationStatus.ECHOUE, DonationStatus.EXPIRE}),
    DonationStatus.EN_ATTENTE: frozenset({DonationStatus.CONFIRME, DonationStatus.ECHOUE, DonationStatus.EXPIRE}),
    DonationStatus.CONFIRME: frozenset({DonationStatus.REMBOURSE}),
    DonationStatus.ECHOUE: frozenset(),
    DonationStatus.EXPIRE: frozenset(),
    DonationStatus.REMBOURSE: frozenset(),
}
# Statuts comptés dans les totaux (un remboursement sort du total).
COUNTED_STATUSES: frozenset[str] = frozenset({DonationStatus.CONFIRME})


class DonationChannel(models.TextChoices):
    EN_LIGNE = "en_ligne", _("En ligne")
    ESPECES = "especes", _("Espèces")


class DonationSource(models.TextChoices):
    """Canal d'entrée d'un don en ligne, déclaré par la page de don (``?src=``) : jamais déduit de
    l'agent utilisateur, ni d'un identifiant d'appareil, ni de l'adresse IP. ``null`` pour les espèces."""

    APP_IOS = "app_ios", _("App iOS")
    APP_ANDROID = "app_android", _("App Android")
    WEB = "web", _("Site")
    QR = "qr", _("QR code")
    INCONNU = "inconnu", _("Non précisé")


class PaymentMethod(models.TextChoices):
    """Moyen constaté (choisi sur la page de l'agrégateur, jamais dans Jàngu Bi)."""

    WAVE = "wave", _("Wave")
    ORANGE_MONEY = "orange_money", _("Orange Money")
    FREE_MONEY = "free_money", _("Free Money")
    CARTE = "carte", _("Carte bancaire")
    ESPECES = "especes", _("Espèces")
    AUTRE = "autre", _("Autre")
    INCONNU = "inconnu", _("Inconnu")


class StatusSource(models.TextChoices):
    CHECKOUT = "checkout", _("Création du paiement")
    WEBHOOK = "webhook", _("Notification de l'agrégateur")
    RECONCILIATION = "reconciliation", _("Réconciliation")
    STAFF = "staff", _("Action du staff")
    SYSTEM = "system", _("Système")


class AttemptStatus(models.TextChoices):
    CREE = "cree", _("Créé")
    EN_ATTENTE = "en_attente", _("En attente")
    REUSSI = "reussi", _("Réussi")
    ECHOUE = "echoue", _("Échoué")
    ANNULE = "annule", _("Annulé")
    EXPIRE = "expire", _("Expiré")


class WebhookStatus(models.TextChoices):
    RECU = "recu", _("Reçu")
    TRAITE = "traite", _("Traité")
    DOUBLON = "doublon", _("Doublon")
    REJETE = "rejete", _("Rejeté (signature)")
    ERREUR = "erreur", _("Erreur de traitement")


class CashCollectionStatus(models.TextChoices):
    SAISIE = "saisie", _("Saisie, à valider")
    VALIDEE = "validee", _("Validée")
    REJETEE = "rejetee", _("Rejetée")


class PayoutStatus(models.TextChoices):
    RECU = "recu", _("Reçu, à rapprocher")
    RAPPROCHE = "rapproche", _("Rapproché")
    ECART = "ecart", _("Écart constaté")


class RemittanceMode(models.TextChoices):
    ESPECES = "especes", _("Espèces remises à la curie")
    VIREMENT = "virement", _("Virement")
    COMPENSATION = "compensation", _("Compensation sur la rétrocession de l'économat")


class RemittanceStatus(models.TextChoices):
    DECLAREE = "declaree", _("Déclarée par la paroisse")
    CONFIRMEE = "confirmee", _("Réception confirmée par la curie")
    CONTESTEE = "contestee", _("Contestée par la curie")
