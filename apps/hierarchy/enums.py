from django.db import models
from django.utils.translation import gettext_lazy as _


class NodeStatus(models.TextChoices):
    EN_FONDATION = "en_fondation", _("En fondation")
    ERIGE = "erige", _("Érigé")
    SUPPRIME = "supprime", _("Supprimé")


class PlaceKind(models.TextChoices):
    EGLISE_PAROISSIALE = "eglise_paroissiale", _("Église paroissiale")
    SUCCURSALE = "succursale", _("Succursale")
    CHAPELLE = "chapelle", _("Chapelle")
    STATION = "station", _("Station")
    SANCTUAIRE = "sanctuaire", _("Sanctuaire")


class ScheduleKind(models.TextChoices):
    MESSE = "messe", _("Messe")
    CONFESSION = "confession", _("Confession")
    ADORATION = "adoration", _("Adoration")


class Weekday(models.IntegerChoices):
    LUNDI = 0, _("Lundi")
    MARDI = 1, _("Mardi")
    MERCREDI = 2, _("Mercredi")
    JEUDI = 3, _("Jeudi")
    VENDREDI = 4, _("Vendredi")
    SAMEDI = 5, _("Samedi")
    DIMANCHE = 6, _("Dimanche")


class RequiredOrder(models.TextChoices):
    AUCUN = "aucun", _("Aucun")
    DIACRE = "diacre", _("Diacre")
    PRETRE = "pretre", _("Prêtre")
    EVEQUE = "eveque", _("Évêque")


class Cardinality(models.TextChoices):
    ONE = "one", _("Un seul titulaire")
    MANY = "many", _("Plusieurs titulaires")


class AssignmentStatus(models.TextChoices):
    PROPOSEE = "proposee", _("Proposée")
    ACTIVE = "active", _("Active")
    TERMINEE = "terminee", _("Terminée")
    ANNULEE = "annulee", _("Annulée")


class OverrideEffect(models.TextChoices):
    RETRAIT = "retrait", _("Retrait")


class EtatDeVie(models.TextChoices):
    LAIC = "laic", _("Laïc")
    CLERC = "clerc", _("Clerc")
    CONSACRE = "consacre", _("Consacré")


class DegreOrdre(models.TextChoices):
    AUCUN = "aucun", _("Aucun")
    DIACRE_TRANSITOIRE = "diacre_transitoire", _("Diacre (transitoire)")
    DIACRE_PERMANENT = "diacre_permanent", _("Diacre permanent")
    PRETRE = "pretre", _("Prêtre")
    EVEQUE = "eveque", _("Évêque")


class StatutVerification(models.TextChoices):
    DECLARE = "declare", _("Déclaré")
    VERIFIE = "verifie", _("Vérifié")
    REJETE = "rejete", _("Rejeté")
    COMPLEMENT = "complement", _("Complément demandé")


# Rang d'ordre : sert à la condition d'ordre des offices (EF-PER-05).
ORDER_RANK = {
    DegreOrdre.AUCUN: 0,
    DegreOrdre.DIACRE_TRANSITOIRE: 1,
    DegreOrdre.DIACRE_PERMANENT: 1,
    DegreOrdre.PRETRE: 2,
    DegreOrdre.EVEQUE: 3,
}
REQUIRED_ORDER_RANK = {
    RequiredOrder.AUCUN: 0,
    RequiredOrder.DIACRE: 1,
    RequiredOrder.PRETRE: 2,
    RequiredOrder.EVEQUE: 3,
}
