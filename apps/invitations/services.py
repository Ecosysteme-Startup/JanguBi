"""Invitations et validation des comptes du clergé (lot V1-routes).

Autorisation : ``comptes.valider`` sur le nœud de l'invitation (diocèse et sous-arbre ; partout pour
la plateforme). Toute action est journalisée (``AuditEvent``). Le compte lui-même vit dans Keycloak :
l'activation ou la désactivation passe par ``apps.users.services_accounts`` (Keycloak + audit).
"""

import datetime
import hashlib
import secrets
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.exceptions import ApplicationError, PermissionDeniedError
from apps.hierarchy import authz
from apps.hierarchy.audit import audit_log
from apps.hierarchy.enums import DegreOrdre, EtatDeVie, StatutVerification
from apps.hierarchy.models import Node
from apps.invitations.models import ClergyInvitation, InvitationStatus

DEFAULT_TTL_DAYS = 14
MAX_TTL_DAYS = 30
PENDING_STATUSES = (StatutVerification.DECLARE, StatutVerification.COMPLEMENT)


class InvitationInvalidError(ApplicationError):
    code = "invitation_invalide"
    status_code = 410


def token_hash(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def accept_url(token: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/accept-invitation?{urlencode({'token': token})}"


def keycloak_register_url(*, token: str, email: str) -> str:
    """Page d'inscription Keycloak (client ``jangubi-web``) qui revient sur la page d'acceptation."""
    params = {
        "client_id": "jangubi-web",
        "response_type": "code",
        "scope": "openid",
        "redirect_uri": accept_url(token),
        "login_hint": email,
    }
    return (
        f"{settings.KEYCLOAK_SERVER_URL}/realms/{settings.KEYCLOAK_REALM}"
        f"/protocol/openid-connect/registrations?{urlencode(params)}"
    )


def _require(actor: Any, node: Node) -> None:
    if not authz.peut(actor, "comptes.valider", node):
        raise PermissionDeniedError("Vous ne gérez pas les comptes de ce nœud.", code="comptes_forbidden")


def _email_send(*, invitation: ClergyInvitation, token: str) -> None:
    from apps.emails.services import send_multi_format_email

    send_multi_format_email(
        template_prefix="invitation_clerge",
        template_ctxt={
            "invitation": invitation,
            "accept_url": accept_url(token),
            "register_url": keycloak_register_url(token=token, email=invitation.email),
        },
        target_email=invitation.email,
        path_prefix="invitations",
    )


@transaction.atomic
def invitation_create(
    *,
    actor: Any,
    node: Node,
    email: str,
    etat_de_vie: str,
    degre_ordre: str = DegreOrdre.AUCUN,
    first_name: str = "",
    last_name: str = "",
    ttl_days: int = DEFAULT_TTL_DAYS,
) -> tuple[ClergyInvitation, str]:
    """Crée l'invitation et envoie le lien par e-mail. Renvoie ``(invitation, jeton)`` : le jeton
    en clair n'est connu qu'ici (réponse de création, e-mail), jamais relu ensuite."""
    _require(actor, node)
    if etat_de_vie == EtatDeVie.LAIC:
        raise ApplicationError("L'invitation concerne un clerc ou un consacré.", code="invitation_laic")
    if etat_de_vie == EtatDeVie.CLERC and degre_ordre == DegreOrdre.AUCUN:
        raise ApplicationError("Indiquez le degré d'ordre du clerc.", code="degre_ordre_required")
    if etat_de_vie == EtatDeVie.CONSACRE and degre_ordre != DegreOrdre.AUCUN:
        raise ApplicationError("Un consacré non ordonné n'a pas de degré d'ordre.", code="degre_ordre_invalid")
    if not 1 <= ttl_days <= MAX_TTL_DAYS:
        raise ApplicationError(f"Validité de 1 à {MAX_TTL_DAYS} jours.", code="ttl_invalid")
    token = secrets.token_urlsafe(32)
    invitation = ClergyInvitation(
        email=email.strip().lower(),
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        node=node,
        etat_de_vie=etat_de_vie,
        degre_ordre=degre_ordre,
        token_hash=token_hash(token),
        expires_at=timezone.now() + datetime.timedelta(days=ttl_days),
        invited_by=actor,
    )
    try:
        with transaction.atomic():
            invitation.save()
    except IntegrityError as exc:
        raise ApplicationError(
            "Une invitation est déjà en attente pour cette adresse sur ce nœud.", code="invitation_duplicate"
        ) from exc
    audit_log(actor=actor, action="compte.invitation", target=invitation, node=node)
    _email_send(invitation=invitation, token=token)
    return invitation, token


@transaction.atomic
def invitation_revoke(*, actor: Any, invitation: ClergyInvitation) -> ClergyInvitation:
    obj = ClergyInvitation.objects.select_for_update().select_related("node").get(pk=invitation.pk)
    _require(actor, obj.node)
    if obj.status != InvitationStatus.EN_ATTENTE:
        raise ApplicationError("Seule une invitation en attente peut être révoquée.", code="invalid_transition")
    obj.status = InvitationStatus.REVOQUEE
    obj.revoked_by = actor
    obj.revoked_at = timezone.now()
    obj.save(update_fields=["status", "revoked_by", "revoked_at", "updated_at"])
    audit_log(actor=actor, action="compte.invitation_revocation", target=obj, node=obj.node)
    return obj


def invitation_from_token(*, token: str, lock: bool = False) -> ClergyInvitation:
    """Invitation en attente et non expirée, sinon 410 ``invitation_invalide``."""
    qs = ClergyInvitation.objects.select_related("node")
    if lock:
        qs = qs.select_for_update()
    invitation = qs.filter(token_hash=token_hash(token)).first()
    if invitation is None or invitation.status != InvitationStatus.EN_ATTENTE:
        raise InvitationInvalidError("Ce lien d'invitation n'est plus valable.")
    if invitation.expires_at <= timezone.now():
        raise InvitationInvalidError("Ce lien d'invitation a expiré. Demandez-en un nouveau au diocèse.", code="invitation_expiree")
    return invitation


@transaction.atomic
def invitation_accept(*, token: str, user: Any) -> ClergyInvitation:
    """La personne, connectée par Keycloak avec l'adresse invitée, accepte : son état de vie est
    déclaré et son compte entre dans la file des comptes en attente de validation."""
    invitation = invitation_from_token(token=token, lock=True)
    if (user.email or "").strip().lower() != invitation.email:
        raise PermissionDeniedError(
            "Connectez-vous avec l'adresse e-mail qui a reçu l'invitation.", code="invitation_email_mismatch"
        )
    now = timezone.now()
    invitation.status = InvitationStatus.ACCEPTEE
    invitation.accepted_by = user
    invitation.accepted_at = now
    invitation.save(update_fields=["status", "accepted_by", "accepted_at", "updated_at"])
    if user.statut_verification != StatutVerification.VERIFIE:
        user.etat_de_vie = invitation.etat_de_vie
        user.degre_ordre = invitation.degre_ordre
        user.statut_verification = StatutVerification.DECLARE
        user.declared_at = now
        user.verification_note = ""
        user.save(update_fields=["etat_de_vie", "degre_ordre", "statut_verification", "declared_at", "verification_note"])
    audit_log(actor=user, action="compte.invitation_acceptation", target=invitation, node=invitation.node)
    _notify(user_ids=[invitation.invited_by_id], event="invitation_acceptee", payload={"invitation_id": str(invitation.pk)})
    return invitation


def _notify(*, user_ids: list[Any], event: str, payload: dict[str, Any]) -> None:
    from apps.messaging.services_notifications import people_notify

    people_notify(user_ids=user_ids, topic=None, event_type=f"compte.{event}", payload=payload)


def account_scope(*, person: Any) -> ClergyInvitation | None:
    """Dernière invitation acceptée par la personne : son nœud fixe qui décide de son compte."""
    return (
        ClergyInvitation.objects.filter(accepted_by=person, status=InvitationStatus.ACCEPTEE)
        .select_related("node")
        .order_by("-accepted_at")
        .first()
    )


def _require_scope(actor: Any, person: Any) -> ClergyInvitation:
    if person.pk == getattr(actor, "pk", None):
        raise PermissionDeniedError("On ne décide pas de son propre compte (RG-07).", code="self_action")
    invitation = account_scope(person=person)
    if invitation is None:
        raise PermissionDeniedError("Ce compte n'a pas été invité par un diocèse.", code="comptes_forbidden")
    _require(actor, invitation.node)
    return invitation


@transaction.atomic
def account_decide(*, actor: Any, person: Any, approve: bool, reason: str = "") -> Any:
    """Valide ou refuse (motif obligatoire) un compte en attente."""
    invitation = _require_scope(actor, person)
    if person.statut_verification not in PENDING_STATUSES:
        raise ApplicationError("Ce compte n'est pas en attente de validation.", code="invalid_transition")
    reason = " ".join((reason or "").split())
    if not approve and not reason:
        raise ApplicationError("Indiquez le motif du refus.", code="reason_required")
    person.statut_verification = StatutVerification.VERIFIE if approve else StatutVerification.REJETE
    person.verification_note = reason[:255]
    person.verified_by = actor
    person.verified_at = timezone.now()
    person.save(update_fields=["statut_verification", "verification_note", "verified_by", "verified_at"])
    authz.invalidate_user(person.pk)
    audit_log(
        actor=actor,
        action="compte.validation" if approve else "compte.refus",
        target=person,
        node=invitation.node,
        metadata={} if approve else {"motif": reason[:255]},
    )
    _notify(user_ids=[person.pk], event="valide" if approve else "refuse", payload={"status": person.statut_verification})
    return person


@transaction.atomic
def account_set_active(*, actor: Any, person: Any, active: bool, ip: str | None = None) -> Any:
    """Active ou désactive le compte (Keycloak et base), journalisé par ``services_accounts``."""
    from apps.users import services_accounts

    invitation = _require_scope(actor, person)
    if active:
        person = services_accounts.account_unlock(account=person, actor=actor, ip=ip)
    else:
        person = services_accounts.account_lock(account=person, actor=actor, ip=ip)
    audit_log(
        actor=actor, action="compte.activation" if active else "compte.desactivation", target=person, node=invitation.node, ip=ip
    )
    return person
