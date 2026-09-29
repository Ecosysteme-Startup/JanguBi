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
    # Nulle : « Pas de date précise » (le secrétariat choisit la messe).
    requested_date = models.DateField(_("date souhaitée"), null=True, blank=True)
    requested_mass = models.CharField(_("messe souhaitée"), max_length=120, blank=True, default="")
    status = models.CharField(max_length=12, choices=IntentionStatus.choices, default=IntentionStatus.RECUE)
    scheduled_date = models.DateField(_("date retenue"), null=True, blank=True)
    scheduled_mass = models.CharField(_("messe retenue"), max_length=120, blank=True, default="")
    # Heure de la messe retenue (issue des horaires du lieu) : sert au décompte par messe et à la feuille.
    scheduled_time = models.TimeField(_("heure de la messe retenue"), null=True, blank=True)
    decided_by = models.ForeignKey("users.BaseUser", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
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


DEFAULT_MAX_PER_MASS = 5


class IntentionSettings(BaseModel):
    """Réglages des intentions d'une paroisse : plafond d'intentions par messe (5 par défaut, ``null`` = sans plafond)."""

    node = models.OneToOneField("hierarchy.Node", on_delete=models.CASCADE, related_name="intention_settings")
    max_per_mass = models.PositiveSmallIntegerField(
        _("intentions par messe au plus"), default=DEFAULT_MAX_PER_MASS, null=True, blank=True
    )

    class Meta:
        verbose_name = _("réglages des intentions")
        verbose_name_plural = _("réglages des intentions")
        constraints = [
            models.CheckConstraint(
                condition=Q(max_per_mass__isnull=True) | (Q(max_per_mass__gte=1) & Q(max_per_mass__lte=50)),
                name="intention_settings_max_range",
            ),
        ]

    def __str__(self) -> str:
        return f"Réglages intentions {self.node_id}"


class MassCapOverride(BaseModel):
    """Plafond propre à une messe : l'horaire hebdomadaire (lieu, jour, heure) ou une messe datée
    (lieu, date, heure). ``max_intentions`` à ``null`` = pas de plafond pour cette messe.
    Priorité : messe datée, puis horaire hebdomadaire, puis réglage de la paroisse."""

    node = models.ForeignKey("hierarchy.Node", on_delete=models.CASCADE, related_name="mass_cap_overrides")
    place = models.ForeignKey("hierarchy.PlaceOfWorship", on_delete=models.CASCADE, related_name="mass_cap_overrides")
    start_time = models.TimeField(_("heure"))
    weekday = models.PositiveSmallIntegerField(_("jour (0 = lundi)"), null=True, blank=True)
    date = models.DateField(_("date"), null=True, blank=True)
    max_intentions = models.PositiveSmallIntegerField(_("intentions au plus"), null=True, blank=True)

    class Meta:
        verbose_name = _("plafond d'une messe")
        verbose_name_plural = _("plafonds des messes")
        constraints = [
            models.CheckConstraint(
                condition=(Q(weekday__isnull=True) & Q(date__isnull=False))
                | (Q(weekday__isnull=False) & Q(date__isnull=True) & Q(weekday__lte=6)),
                name="mass_cap_weekday_xor_date",
            ),
            models.CheckConstraint(
                condition=Q(max_intentions__isnull=True) | (Q(max_intentions__gte=1) & Q(max_intentions__lte=50)),
                name="mass_cap_range",
            ),
            models.UniqueConstraint(
                fields=["place", "weekday", "start_time"], condition=Q(date__isnull=True), name="mass_cap_unique_weekly"
            ),
            models.UniqueConstraint(
                fields=["place", "date", "start_time"], condition=Q(date__isnull=False), name="mass_cap_unique_dated"
            ),
        ]

    def __str__(self) -> str:
        return f"Plafond {self.place_id} {self.date or self.weekday} {self.start_time}"
