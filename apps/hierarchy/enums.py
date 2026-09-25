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
