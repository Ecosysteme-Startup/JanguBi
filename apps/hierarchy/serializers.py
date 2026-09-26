from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.hierarchy.enums import (
    AssignmentStatus,
    DegreOrdre,
    EtatDeVie,
    NodeStatus,
    PlaceKind,
    ScheduleKind,
    StatutVerification,
    Weekday,
)
from apps.hierarchy.models import (
    AuditEvent,
    MassSchedule,
    Node,
    NodeType,
    OfficeAssignment,
    OfficeType,
    PlaceOfWorship,
    ScheduleException,
)
from apps.hierarchy.persons import email_mask, full_name

# --- Sorties -----------------------------------------------------------------


class NodeTypeOutputSerializer(serializers.ModelSerializer):
    allowed_parent_types: serializers.Field = serializers.SlugRelatedField(
        many=True, read_only=True, slug_field="code"
    )

    class Meta:
        model = NodeType
        fields = ["code", "label", "is_territorial", "holds_registers", "order", "allowed_parent_types"]


class NodeTypeRefSerializer(serializers.Serializer):
    code = serializers.CharField()
    # Nom de champ imposé par le contrat d'API ; il masque Field.label (sans effet ici).
    label = serializers.CharField()  # type: ignore[assignment]


class NodeOutputSerializer(serializers.ModelSerializer):
    type = NodeTypeRefSerializer(read_only=True)
    parent_id = serializers.SerializerMethodField(help_text="Identifiant du parent (null pour une racine).")
    has_children = serializers.SerializerMethodField()
    located_in_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = Node
        fields = [
            "id",
            "type",
            "name",
            "code",
            "status",
            "address",
            "city",
            "lat",
            "lng",
            "erected_at",
            "is_active_on_platform",
            "located_in_id",
            "depth",
            "parent_id",
            "has_children",
        ]

    def get_parent_id(self, obj: Node) -> str | None:
        parent_path = obj.path[: -obj.steplen]
        if not parent_path:
            return None
        parents = self.context.get("parent_ids")
        if parents is not None and parent_path in parents:
            return parents[parent_path]
        parent = Node.objects.filter(path=parent_path).values_list("pk", flat=True).first()
        return str(parent) if parent else None

    def get_has_children(self, obj: Node) -> bool:
        return obj.numchild > 0


class NodeRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    code = serializers.CharField()
    type = serializers.CharField(source="type.code")


class PlaceOutputSerializer(serializers.ModelSerializer):
    node_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = PlaceOfWorship
        fields = ["id", "node_id", "name", "kind", "is_main", "address", "city", "lat", "lng", "is_active"]


class ScheduleSerializer(serializers.ModelSerializer):
    weekday = serializers.ChoiceField(choices=Weekday.choices, help_text="0 = lundi … 6 = dimanche")
    kind = serializers.ChoiceField(choices=ScheduleKind.choices, default=ScheduleKind.MESSE)

    class Meta:
        model = MassSchedule
        fields = ["id", "kind", "weekday", "start_time", "end_time", "language", "note", "valid_from", "valid_to"]
        read_only_fields = ["id"]
        extra_kwargs = {
            "end_time": {"required": False, "allow_null": True},
            "language": {"required": False},
            "note": {"required": False},
            "valid_from": {"required": False, "allow_null": True},
            "valid_to": {"required": False, "allow_null": True},
        }


class ScheduleReplaceInputSerializer(serializers.Serializer):
    items = ScheduleSerializer(many=True, help_text="Semaine type complète : remplace les horaires existants.")


class ScheduleExceptionSerializer(serializers.ModelSerializer):
    kind = serializers.ChoiceField(choices=ScheduleKind.choices, default=ScheduleKind.MESSE)

    class Meta:
        model = ScheduleException
        fields = ["id", "date", "kind", "cancelled", "start_time", "end_time", "note"]
        read_only_fields = ["id"]
        extra_kwargs = {
            "cancelled": {"required": False},
            "start_time": {"required": False, "allow_null": True},
            "end_time": {"required": False, "allow_null": True},
            "note": {"required": False},
        }


class OccurrenceOutputSerializer(serializers.Serializer):
    date = serializers.DateField()
    kind = serializers.CharField()
    start_time = serializers.TimeField()
    end_time = serializers.TimeField(allow_null=True)
    place_id = serializers.IntegerField()
    place_name = serializers.CharField()
    language = serializers.CharField()
    note = serializers.CharField()
    is_exception = serializers.BooleanField()


class NodeWeekOutputSerializer(serializers.Serializer):
    node = NodeRefSerializer()
    start = serializers.DateField()
    end = serializers.DateField()
    places = PlaceOutputSerializer(many=True)
    occurrences = OccurrenceOutputSerializer(many=True)


class ImportLineSerializer(serializers.Serializer):
    line = serializers.IntegerField()
    status = serializers.ChoiceField(choices=["ok", "warning", "error"])
    message = serializers.CharField()
    code = serializers.CharField()


class ImportReportSerializer(serializers.Serializer):
    dry_run = serializers.BooleanField()
    applied = serializers.BooleanField()
    valid = serializers.IntegerField()
    warnings = serializers.IntegerField()
    # Nom de champ imposé par le contrat d'API ; il masque Serializer.errors (sérialiseur de sortie seulement).
    errors = serializers.IntegerField()  # type: ignore[assignment]
    lines = ImportLineSerializer(many=True)


# --- Entrées -----------------------------------------------------------------


class NodeFilterSerializer(serializers.Serializer):
    type = serializers.CharField(required=False, help_text="Code du type de nœud")
    # Paramètre de requête imposé par le contrat d'API ; il masque Field.parent (sans effet ici).
    parent = serializers.UUIDField(required=False, help_text="Enfants directs de ce nœud")  # type: ignore[assignment]
    within = serializers.UUIDField(required=False, help_text="Descendants de ce nœud")
    q = serializers.CharField(required=False, help_text="Recherche par nom, ville ou code")
    city = serializers.CharField(required=False)
    status = serializers.ChoiceField(choices=NodeStatus.choices, required=False)
    on_platform = serializers.BooleanField(required=False, allow_null=True, default=None)


class DirectoryFilterSerializer(serializers.Serializer):
    q = serializers.CharField(required=False, help_text="Nom, ville ou code")
    city = serializers.CharField(required=False)
    diocese = serializers.UUIDField(required=False, help_text="Limiter au sous-arbre d'un diocèse")
    type = serializers.CharField(required=False, default="paroisse")
    on_platform = serializers.BooleanField(required=False, allow_null=True, default=None)


class NodeCreateInputSerializer(serializers.Serializer):
    type = serializers.SlugField(help_text="Code du type de nœud")
    name = serializers.CharField(max_length=200)
    parent_id = serializers.UUIDField(required=False, allow_null=True)
    code = serializers.CharField(max_length=64, required=False, allow_blank=True)
    status = serializers.ChoiceField(choices=NodeStatus.choices, default=NodeStatus.ERIGE)
    address = serializers.CharField(required=False, allow_blank=True, default="")
    city = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    lat = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    lng = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    erected_at = serializers.DateField(required=False, allow_null=True)
    is_active_on_platform = serializers.BooleanField(default=False)
    located_in_id = serializers.UUIDField(required=False, allow_null=True)


class NodeUpdateInputSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200, required=False)
    code = serializers.CharField(max_length=64, required=False)
    status = serializers.ChoiceField(choices=NodeStatus.choices, required=False)
    address = serializers.CharField(required=False, allow_blank=True)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    lat = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    lng = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    erected_at = serializers.DateField(required=False, allow_null=True)
    is_active_on_platform = serializers.BooleanField(required=False)
    located_in_id = serializers.UUIDField(required=False, allow_null=True)


class PlaceCreateInputSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    kind = serializers.ChoiceField(choices=PlaceKind.choices, default=PlaceKind.CHAPELLE)
    is_main = serializers.BooleanField(default=False)
    address = serializers.CharField(required=False, allow_blank=True, default="")
    city = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    lat = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    lng = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)


class PlaceUpdateInputSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200, required=False)
    kind = serializers.ChoiceField(choices=PlaceKind.choices, required=False)
    is_main = serializers.BooleanField(required=False)
    address = serializers.CharField(required=False, allow_blank=True)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    lat = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    lng = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False)


class ImportInputSerializer(serializers.Serializer):
    file = serializers.FileField(help_text="Fichier CSV encodé en UTF-8")


class ImportQuerySerializer(serializers.Serializer):
    dry_run = serializers.BooleanField(default=True, help_text="Simulation sans écriture (défaut : true)")


class WeekQuerySerializer(serializers.Serializer):
    start = serializers.DateField(required=False, help_text="Premier jour (par défaut : aujourd'hui)")


# --- Offices, nominations, personnes (L2) -----------------------------------------------


class PersonRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    full_name = serializers.SerializerMethodField()

    def get_full_name(self, obj: Any) -> str:
        profile = getattr(obj, "profile", None)
        name = f"{getattr(profile, 'first_name', '')} {getattr(profile, 'last_name', '')}".strip()
        return name or obj.email


class OfficeTypeOutputSerializer(serializers.ModelSerializer):
    node_types: serializers.Field = serializers.SlugRelatedField(many=True, read_only=True, slug_field="code")
    appointed_by: serializers.Field = serializers.SlugRelatedField(many=True, read_only=True, slug_field="code")
    capabilities: serializers.Field = serializers.SlugRelatedField(many=True, read_only=True, slug_field="code")

    class Meta:
        model = OfficeType
        fields = [
            "code",
            "label",
            "node_types",
            "required_order",
            "cardinality",
            "appointed_by",
            "appointed_by_platform",
            "capabilities",
            "inherits_down",
        ]


class AssignmentOutputSerializer(serializers.ModelSerializer):
    person = PersonRefSerializer(read_only=True)
    office = serializers.CharField(source="office_type.code", read_only=True)
    office_label = serializers.CharField(source="office_type.label", read_only=True)
    node = NodeRefSerializer(read_only=True)
    appointed_by_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = OfficeAssignment
        fields = [
            "id",
            "person",
            "office",
            "office_label",
            "node",
            "start_date",
            "end_date",
            "status",
            "appointed_by_id",
            "decree_ref",
            "note",
            "created_at",
        ]


class AssignmentFilterSerializer(serializers.Serializer):
    node = serializers.UUIDField(required=False, help_text="Sous-arbre de ce nœud")
    person = serializers.UUIDField(required=False)
    status = serializers.ChoiceField(choices=AssignmentStatus.choices, required=False)
    office = serializers.CharField(required=False)


class AssignmentCreateInputSerializer(serializers.Serializer):
    person_id = serializers.UUIDField()
    office = serializers.SlugField(help_text="Code de l'office")
    node_id = serializers.UUIDField()
    start_date = serializers.DateField(required=False, help_text="Par défaut : aujourd'hui")
    end_date = serializers.DateField(required=False, allow_null=True)
    decree_ref = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class AssignmentUpdateInputSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["terminer", "annuler"])
    end_date = serializers.DateField(required=False, allow_null=True, help_text="Terminer : date de fin (défaut : aujourd'hui)")


class AssignmentImportQuerySerializer(serializers.Serializer):
    dry_run = serializers.BooleanField(default=True)
    effective_date = serializers.DateField(help_text="Date d'effet du mouvement")


class CapaciteOutputSerializer(serializers.Serializer):
    capacite = serializers.CharField()
    node_id = serializers.UUIDField(allow_null=True)
    node_name = serializers.CharField()
    node_type = serializers.CharField(help_text="Code du type de nœud ; « plateforme » hors arbre.")
    herite = serializers.BooleanField()
    office = serializers.CharField()


class DeclarationInputSerializer(serializers.Serializer):
    etat_de_vie = serializers.ChoiceField(choices=EtatDeVie.choices)
    degre_ordre = serializers.ChoiceField(choices=DegreOrdre.choices, default=DegreOrdre.AUCUN)
    incardination_node_id = serializers.UUIDField(required=False, allow_null=True)
    institut_node_id = serializers.UUIDField(required=False, allow_null=True)
    attachment_file_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        default=list,
        max_length=5,
        help_text="Justificatifs à ajouter (celebret, lettre d'obédience…), envoyés d'abord via /files/upload/",
    )


class DeclarationAttachmentOutputSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="file.id")
    file_name = serializers.CharField(source="file.original_file_name")
    file_type = serializers.CharField(source="file.file_type")
    url = serializers.SerializerMethodField(help_text="Lien de téléchargement (présigné en stockage S3)")
    created_at = serializers.DateTimeField()

    def get_url(self, obj: Any) -> str | None:
        return obj.file.url if obj.file.file else None


class PersonStatusOutputSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    full_name = serializers.SerializerMethodField(help_text="Prénom et nom ; vide s'ils ne sont pas renseignés")
    etat_de_vie = serializers.CharField()
    degre_ordre = serializers.CharField()
    statut_verification = serializers.ChoiceField(choices=StatutVerification.choices)
    verification_note = serializers.CharField(help_text="Motif du refus ou du complément demandé")
    declared_at = serializers.DateTimeField(allow_null=True, help_text="Date de la dernière déclaration")
    incardination_node = NodeRefSerializer(allow_null=True)
    institut_node = NodeRefSerializer(allow_null=True)
    attachments = serializers.SerializerMethodField()

    def get_full_name(self, obj: Any) -> str:
        return full_name(obj)

    @extend_schema_field(DeclarationAttachmentOutputSerializer(many=True))
    def get_attachments(self, obj: Any) -> list[Any]:
        files = getattr(obj, "declaration_files", None)
        if files is None:
            files = obj.declaration_attachments.filter(file__upload_finished_at__isnull=False).select_related("file")
        return list(DeclarationAttachmentOutputSerializer(files, many=True).data)


class VerificationDecisionInputSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=[StatutVerification.VERIFIE, StatutVerification.REJETE, StatutVerification.COMPLEMENT]
    )
    note = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
        help_text="Motif, obligatoire pour « complement » ; transmis à la personne",
    )


class VerificationFilterSerializer(serializers.Serializer):
    statut = serializers.ChoiceField(
        choices=[StatutVerification.DECLARE, StatutVerification.COMPLEMENT],
        required=False,
        help_text="« declare » : à vérifier ; « complement » : en attente du complément demandé",
    )


class PersonSearchFilterSerializer(serializers.Serializer):
    q = serializers.CharField(min_length=2, max_length=100, help_text="Nom, prénom ou e-mail (2 caractères au moins)")


class PersonSearchOutputSerializer(serializers.Serializer):
    """Juste ce qu'il faut pour choisir la personne à nommer (jamais l'e-mail en clair)."""

    id = serializers.UUIDField()
    full_name = serializers.SerializerMethodField()
    email_masked = serializers.SerializerMethodField()
    etat_de_vie = serializers.CharField()
    degre_ordre = serializers.CharField()
    statut_verification = serializers.ChoiceField(choices=StatutVerification.choices)
    incardination_node = NodeRefSerializer(allow_null=True)

    def get_full_name(self, obj: Any) -> str:
        return full_name(obj)

    def get_email_masked(self, obj: Any) -> str:
        return email_mask(obj.email)


class CapabilityOverrideSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    diocese_node_id = serializers.UUIDField()
    office = serializers.SlugField(source="office_type.code")
    capability = serializers.CharField(source="capability.code")


class AuditEventOutputSerializer(serializers.ModelSerializer):
    actor_id = serializers.UUIDField(read_only=True, allow_null=True)
    node_id = serializers.UUIDField(read_only=True, allow_null=True)
    actor_name = serializers.SerializerMethodField(help_text="Prénom et nom de l'acteur ; null pour une action du système")
    ip = serializers.IPAddressField(
        read_only=True, allow_null=True, help_text="Adresse du client, tronquée (IPv4 /24, IPv6 /48) ; null hors requête"
    )

    class Meta:
        model = AuditEvent
        fields = ["id", "at", "actor_id", "actor_name", "action", "target_type", "target_id", "node_id", "metadata", "ip"]

    def get_actor_name(self, obj: AuditEvent) -> str | None:
        actor = obj.actor
        if actor is None:
            return None
        profile = getattr(actor, "profile", None)
        name = f"{getattr(profile, 'first_name', '')} {getattr(profile, 'last_name', '')}".strip()
        return name or actor.email


class AuditFilterSerializer(serializers.Serializer):
    node = serializers.UUIDField(required=False)
    actor = serializers.UUIDField(required=False)
    action = serializers.CharField(required=False, help_text="Préfixe (ex. office.)")
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
