"""Intentions de messe (lot V1-routes).

AUCUN champ de montant ni de paiement : l'offrande de messe n'est jamais reçue par l'application
(elle se remet à la paroisse). Le texte de l'intention est une donnée religieuse (loi 2008-12) :
jamais dans les journaux ni dans les notifications.
"""

import uuid

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.intentions.enums import IntentionKind, IntentionStatus


class MassIntention(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requester = models.ForeignKey(
        "users.BaseUser", on_delete=models.SET_NULL, null=True, blank=True, related_name="mass_intentions"
    )
    node = models.ForeignKey("hierarchy.Node", on_delete=models.PROTECT, related_name="mass_intentions")
    place = models.ForeignKey(
        "hierarchy.PlaceOfWorship", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    kind = models.CharField(_("nature"), max_length=20, choices=IntentionKind.choices)
    intention = models.CharField(_("intention"), max_length=500)
    # Annoncée sans le nom du demandeur (« à une intention particulière »).
    is_anonymous = models.BooleanField(_("sans mon nom"), default=False)
    requested_date = models.DateField(_("date souhaitée"))
    requested_mass = models.CharField(_("messe souhaitée"), max_length=120, blank=True, default="")
    status = models.CharField(max_length=12, choices=IntentionStatus.choices, default=IntentionStatus.RECUE)
    scheduled_date = models.DateField(_("date retenue"), null=True, blank=True)
    scheduled_mass = models.CharField(_("messe retenue"), max_length=120, blank=True, default="")
    decided_by = models.ForeignKey(
        "users.BaseUser", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    refusal_reason = models.CharField(_("motif du refus"), max_length=300, blank=True, default="")
    celebrated_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("intention de messe")
        verbose_name_plural = _("intentions de messe")
        ordering = ["requested_date", "created_at"]
        indexes = [
            models.Index(fields=["node", "status", "requested_date"], name="intention_node_status_idx"),
            models.Index(fields=["requester", "-created_at"], name="intention_requester_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(status="planifiee") | Q(scheduled_date__isnull=False),
                name="intention_scheduled_has_date",
            ),
        ]

    def __str__(self) -> str:
        return f"Intention {self.pk} ({self.status})"
