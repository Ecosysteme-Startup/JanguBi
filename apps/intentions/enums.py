from django.db import models
from django.utils.translation import gettext_lazy as _

# Règle produit : aucune offrande de messe dans l'application (ni montant, ni paiement). Ce texte
# informatif accompagne chaque réponse destinée au fidèle.
OFFERING_NOTICE = (
    "L'application ne reçoit aucune offrande. Selon l'usage, l'offrande de messe se remet "
    "directement au secrétariat de la paroisse."
)


class IntentionStatus(models.TextChoices):
    RECUE = "recue", _("Reçue")
    PLANIFIEE = "planifiee", _("Planifiée")
    REFUSEE = "refusee", _("Refusée")
    CELEBREE = "celebree", _("Célébrée")
    ANNULEE = "annulee", _("Annulée")


class IntentionKind(models.TextChoices):
    DEFUNT = "defunt", _("Pour un défunt")
    ACTION_DE_GRACES = "action_de_graces", _("Action de grâces")
    PARTICULIERE = "particuliere", _("Intention particulière")


OPEN_STATUSES = (IntentionStatus.RECUE, IntentionStatus.PLANIFIEE)
