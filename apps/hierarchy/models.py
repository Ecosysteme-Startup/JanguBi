import uuid
from typing import TYPE_CHECKING, Any

from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

if TYPE_CHECKING:
    # treebeard n'a pas de stubs : on expose à mypy la partie de MP_Node qu'on utilise,
    # pour que le plugin Django type normalement les champs de Node.
    class MP_Node(models.Model):
        path: str
        depth: int
        numchild: int
        steplen: int

        class Meta:
            abstract = True

        @classmethod
        def add_root(cls, **kwargs: Any) -> Any: ...

        def add_child(self, **kwargs: Any) -> Any: ...

else:
    from treebeard.mp_tree import MP_Node

from apps.common.models import BaseModel
from apps.hierarchy.enums import NodeStatus, PlaceKind, ScheduleKind, Weekday


# Le gestionnaire de Node vient de treebeard (non typé) : le plugin Django ne peut pas le résoudre.
class NodeType(BaseModel):  # type: ignore[django-manager-missing]
    """Type de nœud paramétrable (province, diocèse, doyenné, paroisse…).

    Un type sans parent autorisé est un type racine.
    """

    code = models.SlugField(_("code"), max_length=40, unique=True)
    label = models.CharField(_("libellé"), max_length=100)
    is_territorial = models.BooleanField(_("territorial"), default=True)
    holds_registers = models.BooleanField(
        _("tient des registres"),
        default=False,
        help_text=_("Reçoit les demandes d'actes (paroisse, quasi-paroisse)."),
    )
    order = models.PositiveSmallIntegerField(_("ordre d'affichage"), default=0)
    allowed_parent_types = models.ManyToManyField(
        "self",
        symmetrical=False,
        blank=True,
        related_name="allowed_child_types",
        verbose_name=_("types de parents autorisés"),
    )

    class Meta:
        verbose_name = _("type de nœud")
        verbose_name_plural = _("types de nœuds")
        ordering = ["order", "label"]

    def __str__(self) -> str:
        return self.label


class Node(MP_Node):  # type: ignore[django-manager-missing]  # idem : gestionnaire treebeard
    """Nœud de l'arbre des juridictions (chemin matérialisé treebeard)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.ForeignKey(NodeType, on_delete=models.PROTECT, related_name="nodes", verbose_name=_("type"))
    name = models.CharField(_("nom"), max_length=200)
    code = models.CharField(_("code"), max_length=64, unique=True)
    status = models.CharField(
        _("statut"), max_length=20, choices=NodeStatus.choices, default=NodeStatus.ERIGE, db_index=True
    )
    address = models.TextField(_("adresse"), blank=True, default="")
    city = models.CharField(_("ville"), max_length=100, blank=True, default="", db_index=True)
    lat = models.DecimalField(_("latitude"), max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(_("longitude"), max_digits=9, decimal_places=6, null=True, blank=True)
    erected_at = models.DateField(_("date d'érection"), null=True, blank=True)
    is_active_on_platform = models.BooleanField(_("active sur Jàngu Bi"), default=False, db_index=True)
    located_in = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="located_nodes",
        verbose_name=_("situé dans"),
        help_text=_("Lien géographique d'un nœud non territorial (ex. communauté située dans un diocèse)."),
    )
    legacy_model = models.CharField(_("modèle d'origine"), max_length=40, blank=True, default="")
    legacy_id = models.BigIntegerField(_("identifiant d'origine"), null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("nœud")
        verbose_name_plural = _("nœuds")
        constraints = [
            models.UniqueConstraint(
                fields=["legacy_model", "legacy_id"],
                condition=Q(legacy_id__isnull=False),
                name="hierarchy_node_unique_legacy",
            ),
        ]
        indexes = [models.Index(fields=["type", "status"], name="hierarchy_node_type_status")]

    def __str__(self) -> str:
        return self.name


class PlaceOfWorship(BaseModel):
    """Lieu de culte rattaché à un nœud ; porte les horaires."""

    node = models.ForeignKey(Node, on_delete=models.PROTECT, related_name="places", verbose_name=_("nœud"))
    name = models.CharField(_("nom"), max_length=200)
    kind = models.CharField(_("type"), max_length=30, choices=PlaceKind.choices, default=PlaceKind.CHAPELLE)
    is_main = models.BooleanField(_("lieu principal"), default=False)
    address = models.TextField(_("adresse"), blank=True, default="")
    city = models.CharField(_("ville"), max_length=100, blank=True, default="")
    lat = models.DecimalField(_("latitude"), max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(_("longitude"), max_digits=9, decimal_places=6, null=True, blank=True)
    is_active = models.BooleanField(_("actif"), default=True)
    legacy_id = models.BigIntegerField(_("identifiant d'origine (org.Church)"), null=True, blank=True, unique=True)

    class Meta:
        verbose_name = _("lieu de culte")
        verbose_name_plural = _("lieux de culte")
        ordering = ["-is_main", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["node"], condition=Q(is_main=True), name="hierarchy_place_unique_main_per_node"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class MassSchedule(BaseModel):
    """Horaire récurrent (messe, confession, adoration) d'un lieu de culte."""

    place = models.ForeignKey(PlaceOfWorship, on_delete=models.CASCADE, related_name="schedules")
    kind = models.CharField(_("type"), max_length=20, choices=ScheduleKind.choices, default=ScheduleKind.MESSE)
    weekday = models.PositiveSmallIntegerField(_("jour"), choices=Weekday.choices)
    start_time = models.TimeField(_("début"))
    end_time = models.TimeField(_("fin"), null=True, blank=True)
    language = models.CharField(_("langue"), max_length=20, blank=True, default="fr")
    note = models.CharField(_("note"), max_length=200, blank=True, default="")
    valid_from = models.DateField(_("valable du"), null=True, blank=True)
    valid_to = models.DateField(_("valable jusqu'au"), null=True, blank=True)

    class Meta:
        verbose_name = _("horaire")
        verbose_name_plural = _("horaires")
        ordering = ["weekday", "start_time"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_time__isnull=True) | Q(end_time__gt=F("start_time")),
                name="hierarchy_schedule_end_after_start",
            ),
            models.CheckConstraint(
                condition=Q(valid_to__isnull=True) | Q(valid_from__isnull=True) | Q(valid_to__gte=F("valid_from")),
                name="hierarchy_schedule_valid_range",
            ),
            models.CheckConstraint(condition=Q(weekday__lte=6), name="hierarchy_schedule_weekday_range"),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.get_weekday_display()} {self.start_time:%H:%M}"


class ScheduleException(BaseModel):
    """Exception datée : annulation (d'un horaire ou de tout un type) ou horaire supplémentaire."""

    place = models.ForeignKey(PlaceOfWorship, on_delete=models.CASCADE, related_name="schedule_exceptions")
    date = models.DateField(_("date"), db_index=True)
    kind = models.CharField(_("type"), max_length=20, choices=ScheduleKind.choices, default=ScheduleKind.MESSE)
    cancelled = models.BooleanField(_("annulation"), default=False)
    start_time = models.TimeField(_("début"), null=True, blank=True)
    end_time = models.TimeField(_("fin"), null=True, blank=True)
    note = models.CharField(_("note"), max_length=200, blank=True, default="")

    class Meta:
        verbose_name = _("exception d'horaire")
        verbose_name_plural = _("exceptions d'horaire")
        ordering = ["date", "start_time"]
        constraints = [
            models.CheckConstraint(
                condition=Q(cancelled=True) | Q(start_time__isnull=False),
                name="hierarchy_exception_extra_needs_time",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.date} {self.get_kind_display()}"
