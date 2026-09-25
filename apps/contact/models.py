from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.contact.enums import Fonction


class PresentationRequest(BaseModel):
    """Demande de présentation envoyée depuis le formulaire public « Pour les paroisses »."""

    full_name = models.CharField(_("nom complet"), max_length=150)
    fonction = models.CharField(_("fonction"), max_length=30, choices=Fonction.choices)
    paroisse = models.CharField(_("paroisse"), max_length=200)
    diocese_node = models.ForeignKey(
        "hierarchy.Node",
        verbose_name=_("diocèse"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="presentation_requests",
    )
    telephone = models.CharField(_("téléphone"), max_length=30)
    email = models.EmailField(_("e-mail"), max_length=254)
    message = models.TextField(_("message"), max_length=1000, blank=True, default="")
    consented_at = models.DateTimeField(_("consentement le"))
    cure_informe = models.BooleanField(_("curé informé"), default=False)
    handled_at = models.DateTimeField(_("traitée le"), null=True, blank=True)

    class Meta:
        verbose_name = _("demande de présentation")
        verbose_name_plural = _("demandes de présentation")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.full_name} — {self.paroisse}"
