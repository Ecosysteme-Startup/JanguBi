"""Rendez-vous de confession en présentiel (SRS §3.7, §5.3, §8.3 ; RG-08).

AUCUN champ de contenu : ni motif, ni texte libre du fidèle. La confession ne se fait
jamais par l'application ; seul le rendez-vous y est pris.
"""

from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel


class ConfessionSlotRule(BaseModel):
    """Règle récurrente d'un prêtre sur un lieu (EF-PRE-10)."""

    priest = models.ForeignKey("users.BaseUser", on_delete=models.CASCADE, related_name="confession_rules")
    place = models.ForeignKey("hierarchy.PlaceOfWorship", on_delete=models.CASCADE, related_name="confession_rules")
    weekday = models.PositiveSmallIntegerField(_("jour (0 = lundi)"))
    start_time = models.TimeField(_("début"))
    end_time = models.TimeField(_("fin"))
    slot_minutes = models.PositiveSmallIntegerField(_("durée d'un créneau (minutes)"), default=10)
    valid_from = models.DateField(_("valable du"), null=True, blank=True)
    valid_to = models.DateField(_("valable jusqu'au"), null=True, blank=True)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("règle de créneaux")
        verbose_name_plural = _("règles de créneaux")
        ordering = ["weekday", "start_time"]
        constraints = [
            models.CheckConstraint(condition=Q(end_time__gt=F("start_time")), name="confession_rule_times"),
            models.CheckConstraint(condition=Q(weekday__lte=6), name="confession_rule_weekday"),
            models.CheckConstraint(
                condition=Q(slot_minutes__gte=5) & Q(slot_minutes__lte=60), name="confession_rule_slot_minutes"
            ),
        ]

    def __str__(self) -> str:
        return f"Règle {self.priest_id} @ {self.place_id} ({self.weekday} {self.start_time:%H:%M})"


class ConfessionSlot(BaseModel):
    """Créneau généré sur 4 semaines glissantes."""

    class Status(models.TextChoices):
        LIBRE = "libre", _("Libre")
        RESERVE = "reserve", _("Réservé")
        BLOQUE = "bloque", _("Bloqué")

    rule = models.ForeignKey(ConfessionSlotRule, on_delete=models.SET_NULL, null=True, related_name="slots")
    priest = models.ForeignKey("users.BaseUser", on_delete=models.CASCADE, related_name="confession_slots")
    place = models.ForeignKey("hierarchy.PlaceOfWorship", on_delete=models.CASCADE, related_name="confession_slots")
    starts_at = models.DateTimeField(_("début"), db_index=True)
    ends_at = models.DateTimeField(_("fin"))
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.LIBRE, db_index=True)

    class Meta:
        verbose_name = _("créneau de confession")
        verbose_name_plural = _("créneaux de confession")
        ordering = ["starts_at"]
        constraints = [
            models.UniqueConstraint(fields=["priest", "starts_at"], name="confession_slot_unique_priest_start"),
            models.CheckConstraint(condition=Q(ends_at__gt=F("starts_at")), name="confession_slot_times"),
        ]
        indexes = [models.Index(fields=["place", "status", "starts_at"], name="confession_slot_place_idx")]

    def __str__(self) -> str:
        return f"Créneau {self.starts_at:%Y-%m-%d %H:%M} ({self.status})"


class ConfessionBooking(BaseModel):
    """Réservation d'un créneau. Délibérément SANS champ de contenu (RG-08)."""

    class Status(models.TextChoices):
        RESERVEE = "reservee", _("Réservée")
        ANNULEE_FIDELE = "annulee_fidele", _("Annulée par le fidèle")
        ANNULEE_PRETRE = "annulee_pretre", _("Annulée par le prêtre")
        HONOREE = "honoree", _("Honorée")
        ABSENT = "absent", _("Absent")

    slot = models.ForeignKey(ConfessionSlot, on_delete=models.CASCADE, related_name="bookings")
    person = models.ForeignKey("users.BaseUser", on_delete=models.CASCADE, related_name="confession_bookings")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RESERVEE, db_index=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    # Message du PRÊTRE en cas d'annulation (ex. « empêché »), jamais un texte du fidèle.
    cancel_message = models.CharField(max_length=300, blank=True, default="")
    reminder_day_sent_at = models.DateTimeField(null=True, blank=True)
    reminder_hours_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("réservation de confession")
        verbose_name_plural = _("réservations de confession")
        ordering = ["-created_at"]
        constraints = [
            # Une seule réservation active par créneau (EF-PRE-11).
            models.UniqueConstraint(
                fields=["slot"], condition=Q(status="reservee"), name="confession_booking_one_active_per_slot"
            ),
        ]
        indexes = [models.Index(fields=["person", "status"], name="confession_booking_person_idx")]

    def __str__(self) -> str:
        return f"Réservation {self.slot_id} ({self.status})"
