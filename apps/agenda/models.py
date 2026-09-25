from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel


class Event(BaseModel):
    class EventType(models.TextChoices):
        MASS = "mass", _("Messe")
        CONFERENCE = "conference", _("Conférence")
        RETREAT = "retreat", _("Retraite")
        ORDINATION = "ordination", _("Ordination")
        OTHER = "other", _("Autre")

    class ScopeType(models.TextChoices):
        GLOBAL = "global", _("Mondial")
        DIOCESE = "diocese", _("Diocèse")
        PARISH = "parish", _("Paroisse")
        CHURCH = "church", _("Église")

    title = models.CharField(_("titre"), max_length=200)
    description = models.TextField(_("description"), blank=True)
    event_type = models.CharField(
        _("type"),
        max_length=20,
        choices=EventType.choices,
        default=EventType.OTHER,
        db_index=True,
    )
    start_at = models.DateTimeField(_("début"), db_index=True)
    end_at = models.DateTimeField(_("fin"))
    location = models.CharField(_("lieu"), max_length=300, blank=True)
    organizer = models.ForeignKey(
        "users.BaseUser",
        on_delete=models.SET_NULL,
        null=True,
        related_name="organized_events",
    )
    scope_type = models.CharField(
        _("portée"),
        max_length=20,
        choices=ScopeType.choices,
        default=ScopeType.GLOBAL,
        db_index=True,
    )
    # FK territoriales réelles (Chantier 3b — ex-placeholder scope_id IntegerField).
    scope_diocese = models.ForeignKey(
        "org.Diocese",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="scoped_events",
        db_index=True,
        verbose_name=_("diocèse de portée"),
    )
    scope_parish = models.ForeignKey(
        "org.Parish",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="scoped_events",
        db_index=True,
        verbose_name=_("paroisse de portée"),
    )
    scope_church = models.ForeignKey(
        "org.Church",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="scoped_events",
        db_index=True,
        verbose_name=_("église de portée"),
    )
    # --- Portée V1 (L4) : un nœud, ou rien (global). Les champs scope_* ci-dessus restent jusqu'en L9.
    scope_node = models.ForeignKey(
        "hierarchy.Node",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="events",
        verbose_name=_("nœud de portée"),
    )
    scope_place = models.ForeignKey(
        "hierarchy.PlaceOfWorship",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="events",
        verbose_name=_("lieu de culte"),
    )
    reminder_sent_at = models.DateTimeField(_("rappel envoyé le"), null=True, blank=True)
    max_participants = models.PositiveIntegerField(null=True, blank=True)

    # Annulation DOUCE : un événement supprimé garde ses inscriptions (des fidèles
    # s'y sont engagés et sont prévenus par email) et sort simplement des feeds.
    # Une suppression sèche cascaderait sur EventRegistration et effacerait la
    # trace de qui s'était inscrit — inacceptable pour un acte pastoral public.
    cancelled_at = models.DateTimeField(
        _("annulé le"), null=True, blank=True, db_index=True
    )
    cancelled_by = models.ForeignKey(
        "users.BaseUser",
        verbose_name=_("annulé par"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cancelled_events",
    )

    class Meta:
        ordering = ["start_at"]
        verbose_name = _("Événement")
        verbose_name_plural = _("Événements")
        indexes = [
            models.Index(fields=["start_at", "scope_type"], name="event_start_scope_idx"),
            models.Index(fields=["scope_type", "scope_parish"], name="event_parish_idx"),
            models.Index(fields=["scope_type", "scope_diocese"], name="event_diocese_idx"),
            models.Index(fields=["scope_type", "scope_church"], name="event_church_idx"),
            models.Index(fields=["scope_node", "start_at"], name="event_node_start_idx"),
        ]

    @property
    def is_cancelled(self) -> bool:
        return self.cancelled_at is not None

    def __str__(self) -> str:
        return f"{self.title} ({self.start_at.date()})"


class EventRegistration(BaseModel):
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="registrations",
    )
    user = models.ForeignKey(
        "users.BaseUser",
        on_delete=models.CASCADE,
        related_name="event_registrations",
    )
    registered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [["event", "user"]]
        verbose_name = _("Inscription événement")
        verbose_name_plural = _("Inscriptions événements")

    def __str__(self) -> str:
        return f"Registration({self.user_id} → event {self.event_id})"
