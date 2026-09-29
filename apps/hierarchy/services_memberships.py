"""Paroisses multiples (décisions 6-8 du 29/09/2026) : adhésion libre, une paroisse principale,
des paroisses secondaires ; la paroisse peut retirer un membre.

Invariants tenus ici (et par les contraintes de ``ParishMembership``) :
- au plus une appartenance principale active par fidèle ; dès qu'il a une appartenance active,
  l'une d'elles est principale (la plus ancienne secondaire est promue quand la principale part) ;
- ``BaseUser.paroisse_suivie`` est toujours la copie de la principale (``None`` sans appartenance) ;
- chaque changement invalide les droits en cache (``authz.invalidate_user``), dont le contexte
  d'appartenance de la sonothèque.
"""

from functools import partial
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import ApplicationError, NotFoundError, PermissionDeniedError
from apps.hierarchy import authz
from apps.hierarchy.audit import audit_log
from apps.hierarchy.enums import NodeStatus
from apps.hierarchy.models import Node, ParishMembership

MANAGE = "paroissiens.gerer"


def _invalidate(user_id: Any) -> None:
    authz.invalidate_user(user_id)
    transaction.on_commit(partial(authz.invalidate_user, user_id))


def _parish_check(node: Node) -> None:
    if not node.type.holds_registers:
        raise ApplicationError("Choisissez une paroisse.", code="not_a_parish")
    if node.status == NodeStatus.SUPPRIME:
        raise ApplicationError("Cette paroisse n'existe plus.", code="parish_deleted")


def _active(user: Any) -> Any:
    return ParishMembership.objects.select_for_update().filter(user=user, removed_by_parish_at__isnull=True)


def _adopt_legacy(user: Any) -> None:
    """Un compte dont ``paroisse_suivie`` a été écrit hors de ces services (anciennes données,
    import) reçoit l'appartenance principale correspondante avant tout changement."""
    if user.paroisse_suivie_id is None:
        return
    if not ParishMembership.objects.filter(user=user, node_id=user.paroisse_suivie_id).exists():
        has_primary = _active(user).filter(is_primary=True).exists()
        ParishMembership.objects.create(
            user=user, node_id=user.paroisse_suivie_id, is_primary=not has_primary, joined_at=timezone.now()
        )


def _sync_primary(user: Any) -> ParishMembership | None:
    """Promeut la plus ancienne appartenance active s'il n'y a plus de principale, puis recopie la
    principale dans ``paroisse_suivie``."""
    active = list(_active(user).select_related("node").order_by("joined_at", "created_at"))
    primary = next((m for m in active if m.is_primary), None)
    if primary is None and active:
        primary = active[0]
        primary.is_primary = True
        primary.save(update_fields=["is_primary", "updated_at"])
    node = primary.node if primary is not None else None
    if user.paroisse_suivie_id != (node.pk if node is not None else None):
        user.paroisse_suivie = node
        user.save(update_fields=["paroisse_suivie", "updated_at"])
    _invalidate(user.pk)
    return primary


def _membership_get(*, user: Any, node: Node) -> ParishMembership:
    membership = _active(user).filter(node=node).first()
    if membership is None:
        raise NotFoundError("Vous n'êtes pas membre de cette paroisse.", code="membre_introuvable")
    return membership


@transaction.atomic
def membership_join(*, user: Any, node: Node, primary: bool = False) -> ParishMembership:
    """Ajouter une paroisse (adhésion libre, sans validation). Idempotent. La première paroisse
    devient la principale ; ``primary=True`` en fait la principale tout de suite."""
    _parish_check(node)
    _adopt_legacy(user)
    existing = ParishMembership.objects.select_for_update().filter(user=user, node=node).first()
    if existing is not None and not existing.is_active:
        raise PermissionDeniedError(
            "Cette paroisse vous a retiré de ses membres. Adressez-vous au secrétariat paroissial.",
            code="retire_par_la_paroisse",
        )
    membership = existing or ParishMembership.objects.create(user=user, node=node, joined_at=timezone.now())
    if primary and not membership.is_primary:
        _active(user).filter(is_primary=True).update(is_primary=False, updated_at=timezone.now())
        membership.is_primary = True
        membership.save(update_fields=["is_primary", "updated_at"])
    _sync_primary(user)
    membership.refresh_from_db()
    return membership


@transaction.atomic
def membership_leave(*, user: Any, node: Node) -> None:
    """Retirer une paroisse (le fidèle lui-même). Si c'était la principale, la plus ancienne des
    secondaires la remplace."""
    _adopt_legacy(user)
    _membership_get(user=user, node=node).delete()
    _sync_primary(user)


@transaction.atomic
def membership_set_primary(*, user: Any, node: Node) -> ParishMembership:
    """Une seule principale : l'ancienne devient secondaire."""
    _adopt_legacy(user)
    membership = _membership_get(user=user, node=node)
    if not membership.is_primary:
        _active(user).filter(is_primary=True).update(is_primary=False, updated_at=timezone.now())
        membership.is_primary = True
        membership.save(update_fields=["is_primary", "updated_at"])
    _sync_primary(user)
    return membership


@transaction.atomic
def paroisse_suivie_set(*, person: Any, node: Node | None) -> Any:
    """Route historique ``PUT me/paroisse-suivie/`` : **remplace** la paroisse principale
    (``None`` : ne plus en avoir ; une secondaire est alors promue). Les secondaires sont gardées."""
    if node is not None:
        _parish_check(node)
    _adopt_legacy(person)
    current = _active(person).filter(is_primary=True).first()
    if current is not None and (node is None or current.node_id != node.pk):
        current.delete()
        _sync_primary(person)
    if node is not None:
        membership_join(user=person, node=node, primary=True)
    else:
        _sync_primary(person)
    person.refresh_from_db(fields=["paroisse_suivie"])
    return person


# --- Côté paroisse ------------------------------------------------------------------------------


def _require_manage(actor: Any, node: Node) -> None:
    if not authz.peut(actor, MANAGE, node):
        raise PermissionDeniedError("Vous ne pouvez pas gérer les membres de cette paroisse.", code="membres_forbidden")
    authz.mfa_check(actor)


@transaction.atomic
def membership_remove_by_parish(*, actor: Any, node: Node, user: Any) -> ParishMembership:
    """La paroisse retire un membre (``paroissiens.gerer``). La ligne est gardée : le fidèle ne peut
    plus s'y réinscrire seul. Ses contenus réservés et ses téléchargements hors ligne de cette
    paroisse ne sont plus accessibles (vérification des licences)."""
    _require_manage(actor, node)
    _adopt_legacy(user)
    membership = ParishMembership.objects.select_for_update().filter(user=user, node=node).first()
    if membership is None:
        raise NotFoundError("Cette personne n'est pas membre de la paroisse.", code="membre_introuvable")
    if membership.is_active:
        membership.removed_by_parish_at = timezone.now()
        membership.removed_by = actor
        membership.is_primary = False
        membership.save(update_fields=["removed_by_parish_at", "removed_by", "is_primary", "updated_at"])
        audit_log(actor=actor, action="paroisse.membre_retire", target=membership, node=node)
        _sync_primary(user)
    return membership


@transaction.atomic
def membership_restore_by_parish(*, actor: Any, node: Node, user: Any) -> ParishMembership:
    """Rétablir un membre retiré : il redevient membre (principale s'il n'en a pas d'autre)."""
    _require_manage(actor, node)
    membership = ParishMembership.objects.select_for_update().filter(user=user, node=node).first()
    if membership is None:
        raise NotFoundError("Cette personne n'est pas membre de la paroisse.", code="membre_introuvable")
    if not membership.is_active:
        membership.removed_by_parish_at = None
        membership.removed_by = None
        membership.save(update_fields=["removed_by_parish_at", "removed_by", "updated_at"])
        audit_log(actor=actor, action="paroisse.membre_retabli", target=membership, node=node)
        _sync_primary(user)
        membership.refresh_from_db()
    return membership
