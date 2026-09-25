from django.db import models


class Fonction(models.TextChoices):
    CURE = "cure", "Curé"
    VICAIRE = "vicaire", "Vicaire"
    SECRETAIRE = "secretaire", "Secrétaire paroissial"
    REFERENT_NUMERIQUE = "referent_numerique", "Référent numérique"
    CHANCELIER = "chancelier", "Chancelier"
    EVEQUE = "eveque", "Évêque"
    AUTRE = "autre", "Autre"
