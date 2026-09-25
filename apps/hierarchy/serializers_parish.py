"""Vie paroissiale : paramètres du secrétariat (espace paroisse) et fiche publique enrichie."""

from datetime import time
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.hierarchy.models import Node
from apps.hierarchy.serializers import NodeOutputSerializer

OFFICE_HOURS_MAX_ITEMS = 7
ACTS_DELAY_MAX_DAYS = 90
ACTS_WELCOME_MAX_LENGTH = 1000
PHONE_REGEX = r"^\+?[0-9 ().-]{6,30}$"

# --- Paramètres (espace paroisse) --------------------------------------------------------


class OfficeHoursItemSerializer(serializers.Serializer):
    days = serializers.CharField(max_length=40, help_text="Jours concernés, ex. « Lun. – ven. »")
    hours = serializers.CharField(max_length=120, help_text="Heures, ex. « 9 h-12 h · 15 h 30-18 h » ou « Fermé »")


class NodeSettingsOutputSerializer(serializers.ModelSerializer):
    office_hours = OfficeHoursItemSerializer(many=True)

    class Meta:
        model = Node
        fields = [
            "id",
            "address",
            "city",
            "phone",
            "email",
            "office_hours",
            "secretariat_public",
            "acts_delay_days",
            "acts_welcome_message",
            "updated_at",
        ]


class NodeSettingsUpdateInputSerializer(serializers.Serializer):
    """Champs « vie paroissiale » : modifiables avec ``horaires.gerer`` (ou ``structure.gerer``)."""

    address = serializers.CharField(required=False, allow_blank=True, max_length=300)
    city = serializers.CharField(required=False, allow_blank=True, max_length=100)
    phone = serializers.RegexField(PHONE_REGEX, required=False, allow_blank=True, max_length=30)
    email = serializers.EmailField(required=False, allow_blank=True)
    office_hours = serializers.ListField(
        child=OfficeHoursItemSerializer(), required=False, max_length=OFFICE_HOURS_MAX_ITEMS
    )
    secretariat_public = serializers.BooleanField(
        required=False, help_text="Afficher téléphone, e-mail et horaires d'accueil sur la fiche publique"
    )
    acts_delay_days = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, max_value=ACTS_DELAY_MAX_DAYS, help_text="Jours ouvrés"
    )
    acts_welcome_message = serializers.CharField(
        required=False, allow_blank=True, max_length=ACTS_WELCOME_MAX_LENGTH
    )


# --- Public ----------------------------------------------------------------------------


class PublicNodeOutputSerializer(NodeOutputSerializer):
    """Nœud de l'annuaire public : juridiction et messes du dimanche.

    Contexte attendu (calculé en lot, pas de N+1) : ``lineage`` {chemin: nœud ancêtre},
    ``sunday_masses`` {id du nœud: [heures]}.
    """

    parent_name = serializers.SerializerMethodField()
    deanery_name = serializers.SerializerMethodField(help_text="Doyenné (null s'il n'y en a pas)")
    diocese_name = serializers.SerializerMethodField(help_text="Diocèse (null s'il n'y en a pas)")
    sunday_masses = serializers.SerializerMethodField(
        help_text="Heures des messes du prochain dimanche (aujourd'hui si c'est dimanche), exceptions comprises"
    )

    class Meta(NodeOutputSerializer.Meta):
        fields = [*NodeOutputSerializer.Meta.fields, "parent_name", "deanery_name", "diocese_name", "sunday_masses"]

    def _ancestors(self, obj: Node) -> list[Node]:
        lineage: dict[str, Node] = self.context.get("lineage", {})
        paths = [obj.path[: obj.steplen * i] for i in range(1, obj.depth)]
        return [lineage[p] for p in paths if p in lineage]

    def _ancestor_name(self, obj: Node, type_code: str) -> str | None:
        found = [a for a in self._ancestors(obj) if a.type.code == type_code]
        return found[-1].name if found else None

    def get_parent_name(self, obj: Node) -> str | None:
        parent = self.context.get("lineage", {}).get(obj.path[: -obj.steplen]) if obj.depth > 1 else None
        return parent.name if parent is not None else None

    def get_deanery_name(self, obj: Node) -> str | None:
        return self._ancestor_name(obj, "doyenne")

    def get_diocese_name(self, obj: Node) -> str | None:
        return self._ancestor_name(obj, "diocese")

    @extend_schema_field(serializers.ListField(child=serializers.TimeField()))
    def get_sunday_masses(self, obj: Node) -> list[str]:
        times: list[time] = self.context.get("sunday_masses", {}).get(obj.pk, [])
        return [t.isoformat() for t in times]


class PublicSecretariatSerializer(serializers.Serializer):
    phone = serializers.CharField()
    email = serializers.CharField()
    office_hours = OfficeHoursItemSerializer(many=True)


class PublicClergySerializer(serializers.Serializer):
    name = serializers.CharField()
    office = serializers.CharField(help_text="Libellé de l'office (Curé, Vicaire paroissial…)")


class PublicActsInfoSerializer(serializers.Serializer):
    delay_days = serializers.IntegerField(allow_null=True, source="acts_delay_days")
    welcome_message = serializers.CharField(source="acts_welcome_message")


class PublicNodeDetailOutputSerializer(PublicNodeOutputSerializer):
    """Fiche publique : ajoute le secrétariat (s'il est publié), le clergé et l'accueil des demandes d'actes."""

    secretariat = serializers.SerializerMethodField(help_text="null tant que la paroisse ne l'a pas publié")
    clergy = serializers.SerializerMethodField(help_text="Clercs titulaires d'un office actif sur ce nœud")
    acts = serializers.SerializerMethodField()

    class Meta(PublicNodeOutputSerializer.Meta):
        fields = [*PublicNodeOutputSerializer.Meta.fields, "secretariat", "clergy", "acts"]

    @extend_schema_field(PublicSecretariatSerializer(allow_null=True))
    def get_secretariat(self, obj: Node) -> dict[str, Any] | None:
        if not obj.secretariat_public:
            return None
        return dict(PublicSecretariatSerializer(obj).data)

    @extend_schema_field(PublicClergySerializer(many=True))
    def get_clergy(self, obj: Node) -> list[dict[str, Any]]:
        return list(PublicClergySerializer(self.context.get("clergy", []), many=True).data)

    @extend_schema_field(PublicActsInfoSerializer)
    def get_acts(self, obj: Node) -> dict[str, Any]:
        return dict(PublicActsInfoSerializer(obj).data)
