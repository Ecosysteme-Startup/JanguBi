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
from apps.hierarchy.enums import (
    AssignmentStatus,
    Cardinality,
    NodeStatus,
    OverrideEffect,
    PlaceKind,
    RequiredOrder,
    ScheduleKind,
    Weekday,
)


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
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("nœud")
        verbose_name_plural = _("nœuds")
        constraints = [
        ]
        indexes = [
            models.Index(fields=["type", "status"], name="hierarchy_node_type_status"),
            # path__startswith (sous-arbre, enfants) : l'index unique ne sert pas au LIKE 'x%'
            # sous une collation non-C ; varchar_pattern_ops le permet.
            models.Index(fields=["path"], name="hierarchy_node_path_pattern", opclasses=["varchar_pattern_ops"]),
        ]

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


# --- Offices, nominations, capacités (L2, SRS §5.1, §6) -----------------------------


class Capability(models.Model):
    """Droit applicatif élémentaire. Catalogue fermé (RG-14) : seedé, jamais créé depuis l'interface."""

    code = models.CharField(_("code"), max_length=60, primary_key=True)
    label = models.CharField(_("libellé"), max_length=150)
    description = models.TextField(_("description"), blank=True, default="")
    domain = models.CharField(_("domaine"), max_length=40)

    class Meta:
        verbose_name = _("capacité")
        verbose_name_plural = _("capacités")
        ordering = ["domain", "code"]

    def __str__(self) -> str:
        return self.code


class OfficeType(BaseModel):
    """Fonction ecclésiale ou administrative paramétrable (curé, secrétaire…)."""

    code = models.SlugField(_("code"), max_length=60, unique=True)
    label = models.CharField(_("libellé"), max_length=150)
    node_types = models.ManyToManyField(NodeType, related_name="office_types", verbose_name=_("s'exerce sur"))
    required_order = models.CharField(
        _("ordre requis"), max_length=10, choices=RequiredOrder.choices, default=RequiredOrder.AUCUN
    )
    cardinality = models.CharField(_("titulaires"), max_length=4, choices=Cardinality.choices, default=Cardinality.MANY)
    appointed_by = models.ManyToManyField(
        "self", symmetrical=False, blank=True, related_name="can_appoint", verbose_name=_("nommé par")
    )
    appointed_by_platform = models.BooleanField(
        _("nommé par la plateforme"),
        default=False,
        help_text=_("Nomination saisie par Numerisen (ex. évêque diocésain, nomination romaine)."),
    )
    capabilities = models.ManyToManyField(Capability, blank=True, related_name="office_types")
    inherits_down = models.BooleanField(_("hérite sur le sous-arbre"), default=True)
    is_system = models.BooleanField(_("office du profil par défaut"), default=False)

    class Meta:
        verbose_name = _("type d'office")
        verbose_name_plural = _("types d'office")
        ordering = ["label"]

    def __str__(self) -> str:
        return self.label


class OfficeAssignment(BaseModel):
    """Nomination datée d'une personne à un office sur un nœud (RG-04 : la file suit le nœud)."""

    person = models.ForeignKey(
        "users.BaseUser", on_delete=models.PROTECT, related_name="office_assignments", verbose_name=_("personne")
    )
    office_type = models.ForeignKey(OfficeType, on_delete=models.PROTECT, related_name="assignments")
    node = models.ForeignKey(Node, on_delete=models.PROTECT, related_name="office_assignments")
    start_date = models.DateField(_("début"))
    end_date = models.DateField(_("fin"), null=True, blank=True)
    status = models.CharField(
        _("statut"), max_length=10, choices=AssignmentStatus.choices, default=AssignmentStatus.PROPOSEE, db_index=True
    )
    appointed_by = models.ForeignKey(
        "users.BaseUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments_made",
        verbose_name=_("nommé par"),
    )
    decree_ref = models.CharField(_("référence du décret"), max_length=120, blank=True, default="")
    decree_file = models.ForeignKey(
        "files.File", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name=_("décret")
    )
    note = models.CharField(_("note"), max_length=255, blank=True, default="")

    class Meta:
        verbose_name = _("nomination")
        verbose_name_plural = _("nominations")
        ordering = ["-start_date"]
        indexes = [
            models.Index(fields=["person", "status"], name="hierarchy_assign_person_status"),
            models.Index(fields=["node", "office_type", "status"], name="hierarchy_assign_node_office"),
            # Chemin chaud de l'autorisation : nominations actives d'une personne à une date.
            models.Index(
                fields=["person", "start_date", "end_date"],
                condition=Q(status="active"),
                name="hierarchy_assign_active_person",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__isnull=True) | Q(end_date__gte=F("start_date")),
                name="hierarchy_assignment_dates",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.office_type} — {self.node} ({self.get_status_display()})"


class DeclarationAttachment(BaseModel):
    """Justificatif joint à une déclaration d'état de vie (celebret, lettre d'obédience…).

    Donnée religieuse sensible : visible de la personne et de qui a ``personnes.verifier``
    sur son incardination ; effacée avec le compte."""

    person = models.ForeignKey(
        "users.BaseUser", on_delete=models.CASCADE, related_name="declaration_attachments", verbose_name=_("personne")
    )
    file = models.ForeignKey("files.File", on_delete=models.PROTECT, related_name="+", verbose_name=_("fichier"))

    class Meta:
        verbose_name = _("justificatif de déclaration")
        verbose_name_plural = _("justificatifs de déclaration")
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["person", "file"], name="hierarchy_declaration_attachment_unique"),
        ]

    def __str__(self) -> str:
        return f"Justificatif {self.pk}"


class CapabilityOverride(BaseModel):
    """Retrait d'une capacité à un office dans le sous-arbre d'un diocèse (EF-PER-09)."""

    diocese_node = models.ForeignKey(Node, on_delete=models.CASCADE, related_name="capability_overrides")
    office_type = models.ForeignKey(OfficeType, on_delete=models.CASCADE, related_name="overrides")
    capability = models.ForeignKey(Capability, on_delete=models.CASCADE, related_name="overrides")
    effect = models.CharField(max_length=10, choices=OverrideEffect.choices, default=OverrideEffect.RETRAIT)

    class Meta:
        verbose_name = _("retrait de capacité")
        verbose_name_plural = _("retraits de capacité")
        constraints = [
            models.UniqueConstraint(
                fields=["diocese_node", "office_type", "capability"], name="hierarchy_override_unique"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.diocese_node} : {self.office_type} − {self.capability}"


class AuditEvent(models.Model):
    """Journal d'audit métier, en insertion seule (EF-PER-11). Écrit par les services."""

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        "users.BaseUser", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    action = models.CharField(max_length=80)
    target_type = models.CharField(max_length=80)
    target_id = models.CharField(max_length=64)
    node = models.ForeignKey(Node, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_events")
    metadata = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        verbose_name = _("événement d'audit")
        verbose_name_plural = _("journal d'audit")
        ordering = ["-at"]
        indexes = [
            models.Index(fields=["target_type", "target_id"], name="hierarchy_audit_target"),
            models.Index(fields=["node", "-at"], name="hierarchy_audit_node_at"),
            # Filtre par préfixe d'action (« office. ») sous collation non-C.
            models.Index(fields=["action"], name="hierarchy_audit_action_pattern", opclasses=["varchar_pattern_ops"]),
        ]

    def __str__(self) -> str:
        return f"{self.at:%Y-%m-%d %H:%M} {self.action}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None:
            raise ValueError("Le journal d'audit est en insertion seule.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        raise ValueError("Le journal d'audit est en insertion seule.")
