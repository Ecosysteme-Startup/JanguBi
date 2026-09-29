from typing import Any

from django.utils import timezone
from rest_framework import serializers

from apps.hierarchy.enums import DegreOrdre, EtatDeVie, StatutVerification
from apps.hierarchy.persons import email_mask, full_name
from apps.invitations import services
from apps.invitations.models import ClergyInvitation, InvitationStatus

# --- Entrées ------------------------------------------------------------------------------


class InvitationCreateInputSerializer(serializers.Serializer):
    node = serializers.UUIDField(help_text="Diocèse, paroisse ou autre nœud où la personne servira")
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    etat_de_vie = serializers.ChoiceField(choices=[EtatDeVie.CLERC, EtatDeVie.CONSACRE])
    degre_ordre = serializers.ChoiceField(choices=DegreOrdre.choices, default=DegreOrdre.AUCUN)
    ttl_days = serializers.IntegerField(min_value=1, max_value=services.MAX_TTL_DAYS, default=services.DEFAULT_TTL_DAYS)


class InvitationFilterSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=InvitationStatus.choices, required=False)
    node = serializers.UUIDField(required=False)
    q = serializers.CharField(required=False, allow_blank=True, max_length=100, help_text="E-mail")


class TokenInputSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=200)


class PendingFilterSerializer(serializers.Serializer):
    node = serializers.UUIDField(required=False)


class RefuseInputSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, help_text="Motif du refus (communiqué à la personne)")


# --- Sorties ------------------------------------------------------------------------------


def _status(obj: ClergyInvitation) -> str:
    if obj.status == InvitationStatus.EN_ATTENTE and obj.expires_at <= timezone.now():
        return InvitationStatus.EXPIREE
    return obj.status


class InvitationOutputSerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()
    node = serializers.SerializerMethodField()
    invited_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ClergyInvitation
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "node",
            "etat_de_vie",
            "degre_ordre",
            "status",
            "expires_at",
            "invited_by_name",
            "accepted_at",
            "revoked_at",
            "created_at",
        ]

    def get_status(self, obj: ClergyInvitation) -> str:
        return _status(obj)

    def get_node(self, obj: ClergyInvitation) -> dict[str, Any]:
        return {"id": str(obj.node_id), "name": obj.node.name}

    def get_invited_by_name(self, obj: ClergyInvitation) -> str:
        return full_name(obj.invited_by) or "Jàngu Bi"


class InvitationCreatedOutputSerializer(InvitationOutputSerializer):
    accept_url = serializers.CharField(help_text="Lien d'acceptation (montré une seule fois, aussi envoyé par e-mail)")

    class Meta(InvitationOutputSerializer.Meta):
        fields = [*InvitationOutputSerializer.Meta.fields, "accept_url"]


class InvitationPublicOutputSerializer(serializers.Serializer):
    """Ce que voit la personne invitée avant de se connecter : rien de plus que nécessaire."""

    email_masked = serializers.CharField()
    first_name = serializers.CharField()
    node_name = serializers.CharField()
    etat_de_vie = serializers.CharField()
    degre_ordre = serializers.CharField()
    expires_at = serializers.DateTimeField()
    register_url = serializers.CharField(help_text="Inscription Keycloak, retour sur la page d'acceptation")


def invitation_public_payload(*, invitation: ClergyInvitation, token: str) -> dict[str, Any]:
    return {
        "email_masked": email_mask(invitation.email),
        "first_name": invitation.first_name,
        "node_name": invitation.node.name,
        "etat_de_vie": invitation.etat_de_vie,
        "degre_ordre": invitation.degre_ordre,
        "expires_at": invitation.expires_at,
        "register_url": services.keycloak_register_url(token=token, email=invitation.email),
    }


class ClergyAccountOutputSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    full_name = serializers.SerializerMethodField()
    etat_de_vie = serializers.CharField()
    degre_ordre = serializers.CharField()
    statut_verification = serializers.ChoiceField(choices=StatutVerification.choices)
    verification_note = serializers.CharField()
    declared_at = serializers.DateTimeField(allow_null=True)
    is_active = serializers.BooleanField()
    node = serializers.SerializerMethodField(help_text="Nœud de l'invitation acceptée")

    def get_full_name(self, obj: Any) -> str:
        return full_name(obj)

    def get_node(self, obj: Any) -> dict[str, Any] | None:
        invitation = services.account_scope(person=obj)
        return {"id": str(invitation.node_id), "name": invitation.node.name} if invitation else None
