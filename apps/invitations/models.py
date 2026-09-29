"""Invitations des comptes du clergé (lot V1-routes).

Le diocèse (ou la plateforme) invite un clerc ou un consacré par e-mail ; la personne crée son
compte dans Keycloak (seule authentification, ADR-015) puis accepte l'invitation : son compte entre
dans la file « en attente », où il est validé ou refusé avec un motif. Le jeton n'est stocké que
haché (SHA-256).
"""

import uuid

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.hierarchy.enums import DegreOrdre, EtatDeVie


class InvitationStatus(models.TextChoices):
    EN_ATTENTE = "en_attente", _("En attente")
    ACCEPTEE = "acceptee", _("Acceptée")
    REVOQUEE = "revoquee", _("Révoquée")
    EXPIREE = "expiree", _("Expirée")  # calculé à la lecture, jamais écrit


class ClergyInvitation(BaseModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(_("e-mail"))
    first_name = models.CharField(_("prénom"), max_length=100, blank=True, default="")
    last_name = models.CharField(_("nom"), max_length=100, blank=True, default="")
    node = models.ForeignKey("hierarchy.Node", on_delete=models.PROTECT, related_name="clergy_invitations")
    etat_de_vie = models.CharField(_("état de vie"), max_length=10, choices=EtatDeVie.choices)
    degre_ordre = models.CharField(_("degré d'ordre"), max_length=20, choices=DegreOrdre.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    status = models.CharField(
        max_length=12, choices=InvitationStatus.choices, default=InvitationStatus.EN_ATTENTE, db_index=True
    )
    expires_at = models.DateTimeField(_("expire le"))
    invited_by = models.ForeignKey("users.BaseUser", on_delete=models.PROTECT, related_name="+")
    accepted_by = models.ForeignKey(
        "users.BaseUser", on_delete=models.SET_NULL, null=True, blank=True, related_name="clergy_invitations"
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey("users.BaseUser", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    revoked_at = models.DateTimeField(null=True, blank=True)
    # Pièce justificative facultative (celebret, lettre de l'ordinaire…), déposée par apps/files
    # par l'invitant à la création ou par la personne à l'acceptation.
    justificatif = models.ForeignKey(
        "files.File", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        verbose_name=_("pièce justificative"),
    )

    class Meta:
        verbose_name = _("invitation du clergé")
        verbose_name_plural = _("invitations du clergé")
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["node", "status", "-created_at"], name="invitation_node_status_idx")]
        constraints = [
            # Une seule invitation en attente par adresse et par nœud.
            models.UniqueConstraint(
                fields=["email", "node"], condition=Q(status="en_attente"), name="invitation_one_pending_per_email_node"
            ),
            models.CheckConstraint(condition=~Q(etat_de_vie="laic"), name="invitation_not_laic"),
        ]

    def __str__(self) -> str:
        return f"Invitation {self.email} ({self.status})"
