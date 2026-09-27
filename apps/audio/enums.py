"""Valeurs fermées de la sonothèque (plan suite V2, §5)."""

from django.db import models


class SourceKind(models.TextChoices):
    PAROISSE = "paroisse", "Paroisse"
    CHORALE = "chorale", "Chorale"
    MOUVEMENT = "mouvement", "Mouvement"


class AlbumKind(models.TextChoices):
    ALBUM = "album", "Album"
    MESSE = "messe", "Messe enregistrée"
    HOMELIES = "homelies", "Série d'homélies"
    RETRAITE = "retraite", "Retraite"


class Visibility(models.TextChoices):
    """Du plus ouvert au plus fermé. La visibilité effective d'une piste est la plus fermée de la
    sienne et de celle de son album."""

    PUBLIC = "public", "Public"
    PAROISSE = "paroisse", "Membres de la paroisse"
    PRIVE = "prive", "Privé (brouillon du staff)"


VISIBILITY_RANK = {Visibility.PUBLIC: 0, Visibility.PAROISSE: 1, Visibility.PRIVE: 2}


def most_restrictive(*values: str) -> str:
    return max(values, key=lambda v: VISIBILITY_RANK[Visibility(v)])


class TrackStatus(models.TextChoices):
    BROUILLON = "brouillon", "Brouillon (upload en cours)"
    EN_FILE = "en_file", "En file d'encodage"
    ENCODAGE = "encodage", "Encodage en cours"
    PRET = "pret", "Prêt"
    ECHEC = "echec", "Échec de l'encodage"


class Language(models.TextChoices):
    FR = "fr", "Français"
    WO = "wo", "Wolof"
    LA = "la", "Latin"
    SRR = "srr", "Sérère"
    DYO = "dyo", "Diola"
    EN = "en", "Anglais"
    AUTRE = "autre", "Autre"


class LiturgicalSeason(models.TextChoices):
    """Mêmes codes que ``apps.liturgy.calendar``."""

    AVENT = "avent", "Temps de l'Avent"
    NOEL = "noel", "Temps de Noël"
    CAREME = "careme", "Temps du Carême"
    TRIDUUM = "triduum", "Triduum pascal"
    PAQUES = "paques", "Temps pascal"
    ORDINAIRE = "ordinaire", "Temps ordinaire"


class RenditionKind(models.TextChoices):
    HLS_BAS = "hls_bas", "HLS bas débit (2G/3G)"
    HLS_MOYEN = "hls_moyen", "HLS 64 kb/s"
    HLS_HAUT = "hls_haut", "HLS 128 kb/s"
    MP3 = "mp3", "MP3 128 kb/s (hors ligne)"


class PlayEventKind(models.TextChoices):
    START = "start", "Début d'écoute"
    PROGRESS = "progress", "Progression"
    COMPLETE = "complete", "Écoute complète"
    SKIP = "skip", "Passée"
    LIKE = "like", "Aimée"


class NeighborMethod(models.TextChoices):
    COECOUTE = "coecoute", "Co-écoute"
    CONTENU = "contenu", "Contenu (métadonnées)"


class ReportReason(models.TextChoices):
    DROITS = "droits", "Droits d'auteur"
    INAPPROPRIE = "inapproprie", "Contenu inapproprié"
    QUALITE = "qualite", "Problème de son"
    AUTRE = "autre", "Autre"


class ReportStatus(models.TextChoices):
    OUVERT = "ouvert", "Ouvert"
    RETIRE = "retire", "Contenu retiré"
    REJETE = "rejete", "Sans suite"
