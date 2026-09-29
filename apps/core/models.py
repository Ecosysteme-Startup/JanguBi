"""Modèles transverses du socle. ``SeedRecord`` : trace des objets créés par ``seed_realiste``."""

from django.db import models
from django.utils.translation import gettext_lazy as _


class SeedRecord(models.Model):
    """Objet créé par un lot de données de test (``seed_realiste``). ``--reset`` supprime exactement ce
    qui est tracé ici pour le lot, rien d'autre. Seuls les objets « racines » sont tracés ; leurs
    dépendants (dons d'un fonds, messages d'une conversation…) sont retrouvés par leurs clés."""

    batch = models.CharField(_("lot"), max_length=64)
    seeder = models.CharField(_("semeur"), max_length=64)
    model = models.CharField(_("modèle"), max_length=100)
    object_id = models.CharField(_("identifiant"), max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("objet de données de test")
        verbose_name_plural = _("objets de données de test")
        constraints = [
            models.UniqueConstraint(fields=["batch", "model", "object_id"], name="core_seed_record_uniq"),
        ]
        indexes = [models.Index(fields=["batch", "seeder", "model"], name="core_seed_record_lookup")]

    def __str__(self) -> str:
        return f"{self.batch}:{self.model}:{self.object_id}"
