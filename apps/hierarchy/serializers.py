from rest_framework import serializers

from apps.hierarchy.enums import NodeStatus, PlaceKind, ScheduleKind, Weekday
from apps.hierarchy.models import MassSchedule, Node, NodeType, PlaceOfWorship, ScheduleException

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
    status = serializers.ChoiceField(choices=["ok", "error"])
    message = serializers.CharField()
    code = serializers.CharField()


class ImportReportSerializer(serializers.Serializer):
    dry_run = serializers.BooleanField()
    applied = serializers.BooleanField()
    valid = serializers.IntegerField()
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
