import re

from rest_framework import serializers

from apps.contact.enums import Fonction

_PHONE = re.compile(r"^\+?[0-9 ().-]{6,30}$")


def _single_line(value: str) -> None:
    if any(ch in value for ch in "\r\n\t\x00"):
        raise serializers.ValidationError("Ce champ doit tenir sur une seule ligne.")


class PresentationRequestInputSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=150, validators=[_single_line], help_text="Nom et prénom")
    fonction = serializers.ChoiceField(choices=Fonction.choices, help_text="Fonction dans la paroisse ou le diocèse")
    paroisse = serializers.CharField(max_length=200, validators=[_single_line], help_text="Nom de la paroisse")
    diocese_node_id = serializers.UUIDField(
        required=False, allow_null=True, default=None, help_text="Nœud de type diocèse, ou null"
    )
    telephone = serializers.CharField(max_length=30, validators=[_single_line], help_text="Téléphone")
    email = serializers.EmailField(help_text="Adresse e-mail de contact")
    message = serializers.CharField(
        max_length=1000, required=False, allow_blank=True, default="", help_text="Message libre (1 000 caractères max.)"
    )
    consentement = serializers.BooleanField(help_text="Consentement au traitement des données (doit être vrai)")
    cure_informe = serializers.BooleanField(help_text="Le curé est informé de la démarche")

    def validate_telephone(self, value: str) -> str:
        if not _PHONE.match(value.strip()):
            raise serializers.ValidationError("Numéro de téléphone invalide.")
        return value.strip()

    def validate_consentement(self, value: bool) -> bool:
        if value is not True:
            raise serializers.ValidationError("Le consentement est obligatoire.")
        return value


class PresentationRequestOutputSerializer(serializers.Serializer):
    received = serializers.BooleanField()
