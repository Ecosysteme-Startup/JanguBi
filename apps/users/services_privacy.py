"""Conformité (SRS §3.9 EF-CONF-01 à 03 ; ADR-011, loi 2008-12).

- Consentement explicite horodaté, lié à la version en vigueur des CGU et de la politique.
- Suppression du compte : anonymisation de l'identité, purge des conversations, annulation
  de ce qui est en cours, conservation des traces légales anonymisées (références, statuts,
  dates, journal d'audit). Irréversible.
"""

import datetime
import logging
from functools import partial
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import ApplicationError, ConflictError

logger = logging.getLogger(__name__)
ANONYMIZED = "Anonymisé"
ANONYMIZED_BIRTH = datetime.date(1900, 1, 1)
DOCUMENT_ACTIVE_STATUSES = ("submitted", "under_verification", "info_requested", "ready_for_pickup")


@transaction.atomic
def consent_give(*, user: Any, version: str) -> Any:
    """EF-CONF-01 : on n'accepte que la version en vigueur (pas de consentement à un texte périmé)."""
    if version != settings.CONSENT_CURRENT_VERSION:
        raise ApplicationError(
            "Cette version des conditions n'est plus en vigueur.",
            {"current_version": settings.CONSENT_CURRENT_VERSION},
            code="consent_version_outdated",
        )
    user.consent_version = version
    user.consent_at = timezone.now()
    user.save(update_fields=["consent_version", "consent_at", "updated_at"])
    from apps.hierarchy.audit import audit_log

    audit_log(actor=user, action="conformite.consentement", target=user, metadata={"version": version})
    return user


def consent_required(*, user: Any) -> bool:
    return user.consent_version != settings.CONSENT_CURRENT_VERSION or user.consent_at is None


def _active_offices(user: Any) -> bool:
    from apps.hierarchy.authz import active_assignments

    return active_assignments(user=user).exists()


def _storage_delete_on_commit(file_fields: list[Any]) -> None:
    """Suppression des octets APRÈS validation : un retour arrière ne laisse pas une base
    qui pointe vers des fichiers déjà effacés."""
    targets = [(f.storage, f.name) for f in file_fields if f]
    transaction.on_commit(lambda: [storage.delete(name) for storage, name in targets])


def _files_delete(file_objs: list[Any]) -> None:
    _storage_delete_on_commit([f.file for f in file_objs if f is not None])
    for file_obj in file_objs:
        if file_obj is not None:
            file_obj.delete()


def _purge_conversations(user: Any) -> int:
    from django.db.models import Q

    from apps.messaging.models import Conversation, ConversationExport, MessageAttachment

    conversations = Conversation.objects.filter(Q(participant_a=user) | Q(participant_b=user))
    files: list[Any] = [
        a.file for a in MessageAttachment.objects.filter(message__conversation__in=conversations).select_related("file")
    ]
    files += [
        e.json_file
        for e in ConversationExport.objects.filter(conversation__in=conversations).select_related("json_file")
        if e.json_file_id
    ]
    count = conversations.count()
    conversations.delete()
    _files_delete(files)
    return count


def _anonymize_document_requests(user: Any, now: datetime.datetime) -> int:
    from apps.documents.models import DocumentRequest, DocumentRequestAttachment, DocumentRequestStatusLog, InternalNote

    requests = DocumentRequest.objects.filter(requester=user)
    for request_obj in requests.filter(status__in=DOCUMENT_ACTIVE_STATUSES):
        DocumentRequestStatusLog.objects.create(
            request=request_obj, from_status=request_obj.status, to_status="cancelled", comment="Compte supprimé."
        )
    requests.filter(status__in=DOCUMENT_ACTIVE_STATUSES).update(status="cancelled", closed_at=now, updated_at=now)
    attachments = list(DocumentRequestAttachment.objects.filter(request__in=requests).select_related("file"))
    DocumentRequestAttachment.objects.filter(pk__in=[a.pk for a in attachments]).delete()
    _files_delete([a.file for a in attachments])
    InternalNote.objects.filter(request__in=requests).delete()
    DocumentRequestStatusLog.objects.filter(request__in=requests).update(comment="")
    return requests.update(
        requester_last_name=ANONYMIZED,
        requester_first_names=ANONYMIZED,
        date_of_birth=ANONYMIZED_BIRTH,
        place_of_birth="",
        contact_phone="",
        contact_email="",
        registered_last_name="",
        registered_first_names="",
        father_last_name="",
        mother_last_name="",
        sacrament_location="",
        additional_info="",
        document_details={},
        rejection_reason="",
        pickup_message="",
        register_marginal_notes="",
        updated_at=now,
    )


def _release_bookings_and_registrations(user: Any, now: datetime.datetime) -> None:
    from apps.agenda.models import EventRegistration
    from apps.confessions.models import ConfessionBooking, ConfessionSlot

    future = ConfessionBooking.objects.filter(person=user, status="reservee", slot__starts_at__gt=now)
    ConfessionSlot.objects.filter(pk__in=future.values("slot_id"), status="reserve").update(
        status="libre", updated_at=now
    )
    future.update(status="annulee_fidele", cancelled_at=now, updated_at=now)
    EventRegistration.objects.filter(user=user, event__start_at__gt=now).delete()


def _forget_traces(user: Any) -> None:
    from django.db.models import Q

    from apps.messaging.models import (
        ClergicalMessage,
        MessageBlock,
        MessageReaction,
        MessagingAvailability,
        MessagingCguAcceptance,
        Notification,
        NotificationPreference,
        PushDevice,
    )
    from apps.news.models import ArticleReaction, ArticleRead

    MessageBlock.objects.filter(Q(blocker=user) | Q(blocked=user)).delete()
    MessageReaction.objects.filter(user=user).delete()
    MessagingCguAcceptance.objects.filter(user=user).delete()
    PushDevice.objects.filter(user=user).delete()
    ClergicalMessage.objects.filter(Q(sender=user) | Q(individual_recipient=user)).delete()
    ArticleReaction.objects.filter(user=user).delete()
    Notification.objects.filter(user=user).delete()
    NotificationPreference.objects.filter(user=user).delete()
    MessagingAvailability.objects.filter(user=user).delete()
    ArticleRead.objects.filter(user=user).delete()


def _anonymize_identity(user: Any) -> str | None:
    from apps.hierarchy.enums import DegreOrdre, EtatDeVie

    keycloak_sub = user.keycloak_sub
    user.is_active = False
    # État de vie et degré d'ordre : donnée religieuse sensible, effacée aussi.
    user.etat_de_vie = EtatDeVie.LAIC
    user.degre_ordre = DegreOrdre.AUCUN
    user.incardination_node = None
    user.institut_node = None
    user.email = f"deleted_{user.id}@deleted.invalid"
    user.phone_number = None
    user.keycloak_sub = None
    user.paroisse_suivie = None
    user.last_seen_on = None
    user.last_mfa_on = None
    user.set_unusable_password()
    user.save(
        update_fields=[
            "is_active", "email", "phone_number", "keycloak_sub", "paroisse_suivie", "last_seen_on",
            "last_mfa_on", "etat_de_vie", "degre_ordre", "incardination_node", "institut_node",
            "password", "updated_at",
        ]
    )  # fmt: skip
    profile = getattr(user, "profile", None)
    if profile is not None:
        _storage_delete_on_commit([profile.avatar])
        profile.first_name = profile.last_name = ""
        profile.date_of_birth = None
        profile.phone = None
        profile.avatar = None
        profile.save(update_fields=["first_name", "last_name", "date_of_birth", "phone", "avatar", "updated_at"])
    return keycloak_sub


@transaction.atomic
def account_delete(*, user: Any) -> None:
    """EF-CONF-03 : suppression par la personne elle-même. Un titulaire d'office doit d'abord
    voir ses nominations prendre fin (sinon les files de son nœud perdraient un responsable
    sans que l'autorité de nomination le sache)."""
    from apps.hierarchy.audit import audit_log

    if not user.is_active:
        raise ApplicationError("Ce compte est déjà supprimé.", code="account_deleted")
    if _active_offices(user):
        raise ConflictError(
            "Vous avez une nomination en cours : demandez d'abord qu'elle prenne fin.", code="active_office"
        )
    now = timezone.now()
    conversations = _purge_conversations(user)
    documents = _anonymize_document_requests(user, now)
    _release_bookings_and_registrations(user, now)
    _forget_traces(user)
    keycloak_sub = _anonymize_identity(user)
    audit_log(
        actor=user,
        action="conformite.suppression_compte",
        target=user,
        metadata={"conversations_purgees": conversations, "demandes_anonymisees": documents},
    )
    if keycloak_sub:
        from apps.authentication.tasks import keycloak_user_delete_task

        transaction.on_commit(partial(keycloak_user_delete_task.delay, keycloak_sub))
