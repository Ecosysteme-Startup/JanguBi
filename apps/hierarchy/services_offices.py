"""Nominations, vérification de l'état de vie et retraits de capacités (SRS §3.2, §8.2)."""

from datetime import date, timedelta
from functools import partial
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.exceptions import ApplicationError, PermissionDeniedError
from apps.hierarchy import authz
from apps.hierarchy.audit import audit_log
from apps.hierarchy.enums import (
    ORDER_RANK,
    REQUIRED_ORDER_RANK,
    AssignmentStatus,
    Cardinality,
    DegreOrdre,
    EtatDeVie,
    RequiredOrder,
    StatutVerification,
)
from apps.hierarchy.models import Capability, CapabilityOverride, Node, OfficeAssignment, OfficeType
from apps.hierarchy.selectors import node_ancestors

OPEN_STATUSES = (AssignmentStatus.PROPOSEE, AssignmentStatus.ACTIVE)


def _invalidate(user_id: Any) -> None:
    """Invalide les droits en cache tout de suite (même transaction) et après validation
    (une requête concurrente a pu recalculer l'ancien état entre-temps), puis resynchronise
    le rôle Keycloak ``staff`` (EF-AUTH-04)."""
    authz.invalidate_user(user_id)
    transaction.on_commit(partial(authz.invalidate_user, user_id))
    transaction.on_commit(partial(_staff_sync_enqueue, user_id))


def _staff_sync_enqueue(user_id: Any) -> None:
    from django.conf import settings

    if not settings.KEYCLOAK_ENABLED:
        return
    from apps.authentication.tasks import keycloak_staff_sync_task

    keycloak_staff_sync_task.delay(str(user_id))


# --- Contrôles -------------------------------------------------------------------------


def appointing_authority_check(*, actor: Any, office_type: OfficeType, node: Node) -> None:
    """EF-PER-04 : seul un titulaire d'un office « nommeur » sur le nœud ou un ancêtre, avec
    ``offices.nommer``, peut nommer. L'administrateur plateforme peut tout nommer (mode pilote)."""
    if authz.is_platform_admin(actor):
        return
    if office_type.appointed_by_platform:
        raise PermissionDeniedError(
            f"La nomination « {office_type.label} » est saisie par la plateforme.", code="appointment_forbidden"
        )
    if not authz.peut(actor, "offices.nommer", node):
        raise PermissionDeniedError("Vous ne pouvez pas nommer sur ce nœud.", code="appointment_forbidden")
    allowed = set(office_type.appointed_by.values_list("pk", flat=True))
    lineage = [*node_ancestors(node=node), node]
    holds = authz.active_assignments(user=actor).filter(office_type_id__in=allowed, node__in=lineage).exists()
    if not holds:
        raise PermissionDeniedError(
            f"Votre office ne permet pas de nommer « {office_type.label} ».", code="appointment_forbidden"
        )


def _order_check(*, person: Any, office_type: OfficeType) -> None:
    required = office_type.required_order
    if required == RequiredOrder.AUCUN:
        return
    if ORDER_RANK[DegreOrdre(person.degre_ordre)] < REQUIRED_ORDER_RANK[RequiredOrder(required)]:
        raise ApplicationError(
            f"L'office « {office_type.label} » requiert l'ordre : {RequiredOrder(required).label.lower()}.",
            {"required_order": required, "degre_ordre": person.degre_ordre},
            code="order_required",
        )
    if person.statut_verification != StatutVerification.VERIFIE:
        raise ApplicationError(
            "Le statut clérical de la personne doit d'abord être vérifié par la chancellerie.",
            code="clerical_status_not_verified",
        )


def node_type_check(*, office_type: OfficeType, node: Node) -> None:
    if not office_type.node_types.filter(pk=node.type_id).exists():
        raise ApplicationError(
            f"L'office « {office_type.label} » ne s'exerce pas sur un nœud « {node.type.label} ».",
            code="office_node_type_mismatch",
        )


def _overlapping(*, office_type: OfficeType, node: Node, start: date, end: date | None, exclude: int | None = None):
    qs = OfficeAssignment.objects.filter(office_type=office_type, node=node, status__in=OPEN_STATUSES)
    qs = qs.filter(Q(end_date__isnull=True) | Q(end_date__gte=start))
    if end is not None:
        qs = qs.filter(start_date__lte=end)
    if exclude is not None:
        qs = qs.exclude(pk=exclude)
    return qs


def cardinality_check(*, office_type: OfficeType, node: Node, start: date, end: date | None) -> None:
    if office_type.cardinality != Cardinality.ONE:
        return
    if _overlapping(office_type=office_type, node=node, start=start, end=end).exists():
        raise ApplicationError(
            f"« {node.name} » a déjà un titulaire pour l'office « {office_type.label} » sur cette période.",
            code="cardinality_exceeded",
        )


# --- Nominations -------------------------------------------------------------------------


@transaction.atomic
def assignment_create(
    *,
    actor: Any,
    person: Any,
    office_type: OfficeType,
    node: Node,
    start_date: date | None = None,
    end_date: date | None = None,
    decree_ref: str = "",
    decree_file: Any = None,
    note: str = "",
    ip: str | None = None,
) -> OfficeAssignment:
    start_date = start_date or timezone.localdate()
    if end_date is not None and end_date < start_date:
        raise ApplicationError("La fin précède le début.", code="invalid_dates")
    # Personne ne se nomme soi-même : sinon un évêque se ferait vicaire pour obtenir
    # messagerie.recevoir_fideles, que son office exclut volontairement.
    if getattr(actor, "pk", None) == person.pk and not authz.is_platform_admin(actor):
        raise PermissionDeniedError("On ne se nomme pas soi-même à un office.", code="self_appointment")
    appointing_authority_check(actor=actor, office_type=office_type, node=node)
    node_type_check(office_type=office_type, node=node)
    _order_check(person=person, office_type=office_type)
    # Verrou sur le nœud : deux nominations concurrentes au même office ne passent pas toutes les deux.
    Node.objects.select_for_update().filter(pk=node.pk).first()
    cardinality_check(office_type=office_type, node=node, start=start_date, end=end_date)

    status = AssignmentStatus.ACTIVE if start_date <= timezone.localdate() else AssignmentStatus.PROPOSEE
    assignment = OfficeAssignment.objects.create(
        person=person,
        office_type=office_type,
        node=node,
        start_date=start_date,
        end_date=end_date,
        status=status,
        appointed_by=actor if getattr(actor, "is_authenticated", False) else None,
        decree_ref=decree_ref,
        decree_file=decree_file,
        note=note,
    )
    audit_log(
        actor=actor,
        action="office.nomination",
        target=assignment,
        node=node,
        metadata={"office": office_type.code, "person": str(person.pk), "start": str(start_date), "status": status},
        ip=ip,
    )
    _invalidate(person.pk)
    return assignment


@transaction.atomic
def assignment_terminate(
    *, actor: Any, assignment: OfficeAssignment, end_date: date | None = None, ip: str | None = None
) -> OfficeAssignment:
    """Termine une nomination. Sans date (ou à aujourd'hui) : effet immédiat (EF-PER-06, SRS §6.4)."""
    appointing_authority_check(actor=actor, office_type=assignment.office_type, node=assignment.node)
    if assignment.status not in OPEN_STATUSES:
        raise ApplicationError("Cette nomination n'est plus en cours.", code="assignment_closed")
    today = timezone.localdate()
    end_date = end_date or today
    if end_date < assignment.start_date:
        raise ApplicationError("La fin précède le début.", code="invalid_dates")
    assignment.end_date = end_date
    if end_date <= today:
        assignment.status = AssignmentStatus.TERMINEE
    assignment.save(update_fields=["end_date", "status", "updated_at"])
    audit_log(
        actor=actor,
        action="office.fin",
        target=assignment,
        node=assignment.node,
        metadata={"end": str(end_date), "status": assignment.status},
        ip=ip,
    )
    _invalidate(assignment.person_id)
    return assignment


@transaction.atomic
def assignment_cancel(*, actor: Any, assignment: OfficeAssignment, ip: str | None = None) -> OfficeAssignment:
    appointing_authority_check(actor=actor, office_type=assignment.office_type, node=assignment.node)
    if assignment.status != AssignmentStatus.PROPOSEE:
        raise ApplicationError("Seule une nomination proposée peut être annulée.", code="assignment_not_proposed")
    assignment.status = AssignmentStatus.ANNULEE
    assignment.save(update_fields=["status", "updated_at"])
    audit_log(actor=actor, action="office.annulation", target=assignment, node=assignment.node, ip=ip)
    _invalidate(assignment.person_id)
    return assignment


@transaction.atomic
def assignments_sync_statuses(*, today: date | None = None) -> dict[str, int]:
    """Tâche quotidienne (EF-PER-06) : active les nominations arrivées à échéance, termine les échues."""
    today = today or timezone.localdate()
    counts = {"activated": 0, "terminated": 0}
    to_activate = OfficeAssignment.objects.select_for_update().filter(
        status=AssignmentStatus.PROPOSEE, start_date__lte=today
    ).filter(Q(end_date__isnull=True) | Q(end_date__gte=today))
    to_terminate = OfficeAssignment.objects.select_for_update().filter(
        status__in=OPEN_STATUSES, end_date__lt=today
    )
    for assignment, status, key in [
        *((a, AssignmentStatus.ACTIVE, "activated") for a in to_activate.select_related("node")),
        *((a, AssignmentStatus.TERMINEE, "terminated") for a in to_terminate.select_related("node")),
    ]:
        assignment.status = status
        assignment.save(update_fields=["status", "updated_at"])
        audit_log(actor=None, action=f"office.{key}", target=assignment, node=assignment.node, metadata={"on": str(today)})
        counts[key] += 1
        _invalidate(assignment.person_id)
    return counts


def previous_holder_end(*, office_type: OfficeType, node: Node, start: date) -> list[OfficeAssignment]:
    """Titulaires en cours d'un office à titulaire unique qu'il faut clore la veille de ``start``."""
    if office_type.cardinality != Cardinality.ONE:
        return []
    return list(_overlapping(office_type=office_type, node=node, start=start, end=None).filter(start_date__lt=start))


# --- État de vie et vérification (EF-PER-01, -02 ; RG-07) ------------------------------------


@transaction.atomic
def person_declaration_submit(
    *,
    person: Any,
    etat_de_vie: str,
    degre_ordre: str = DegreOrdre.AUCUN,
    incardination_node: Node | None = None,
    institut_node: Node | None = None,
) -> Any:
    if etat_de_vie == EtatDeVie.LAIC and degre_ordre != DegreOrdre.AUCUN:
        raise ApplicationError("Un laïc n'a pas de degré d'ordre.", code="invalid_declaration")
    if etat_de_vie == EtatDeVie.CLERC and degre_ordre == DegreOrdre.AUCUN:
        raise ApplicationError("Indiquez votre degré d'ordre.", code="invalid_declaration")
    if incardination_node is not None and incardination_node.type.code not in {"diocese", "institut"}:
        raise ApplicationError("L'incardination se fait dans un diocèse ou un institut.", code="invalid_declaration")
    if institut_node is not None and institut_node.type.code not in {"institut", "province_religieuse", "communaute"}:
        raise ApplicationError("Choisissez un institut de vie consacrée.", code="invalid_declaration")

    person.etat_de_vie = etat_de_vie
    person.degre_ordre = degre_ordre
    person.incardination_node = incardination_node
    person.institut_node = institut_node
    # Toute déclaration (même modifiée après vérification) repasse en « déclaré » : aucun effet sur les droits.
    person.statut_verification = StatutVerification.DECLARE
    person.verified_by = None
    person.verified_at = None
    person.save(
        update_fields=[
            "etat_de_vie",
            "degre_ordre",
            "incardination_node",
            "institut_node",
            "statut_verification",
            "verified_by",
            "verified_at",
        ]
    )
    audit_log(
        actor=person,
        action="personne.declaration",
        target=person,
        node=incardination_node or institut_node,
        metadata={"etat_de_vie": etat_de_vie, "degre_ordre": degre_ordre},
    )
    return person


def verification_node(person: Any) -> Node | None:
    """Nœud dont l'autorité vérifie la personne : incardination (clerc) ou institut (consacré)."""
    return person.incardination_node or person.institut_node


@transaction.atomic
def person_verification_decide(
    *, actor: Any, person: Any, decision: str, note: str = "", ip: str | None = None
) -> Any:
    if decision not in {StatutVerification.VERIFIE, StatutVerification.REJETE}:
        raise ApplicationError("Décision invalide.", code="invalid_decision")
    if person.pk == actor.pk:
        raise PermissionDeniedError("On ne vérifie pas son propre statut (RG-07).", code="self_verification")
    if person.etat_de_vie == EtatDeVie.LAIC:
        raise ApplicationError("Rien à vérifier pour un laïc.", code="nothing_to_verify")
    node = verification_node(person)
    allowed = authz.peut(actor, "personnes.verifier", node) if node else authz.peut(actor, "personnes.verifier", None)
    if not allowed:
        raise PermissionDeniedError("Vous ne pouvez pas vérifier cette personne.", code="verification_forbidden")

    person.statut_verification = decision
    person.verification_note = note[:255]
    person.verified_by = actor
    person.verified_at = timezone.now()
    person.save(update_fields=["statut_verification", "verification_note", "verified_by", "verified_at"])
    audit_log(actor=actor, action="personne.verification", target=person, node=node, metadata={"decision": decision}, ip=ip)
    return person


# --- Paroisse suivie (RG-01) ----------------------------------------------------------


@transaction.atomic
def paroisse_suivie_set(*, person: Any, node: Node | None) -> Any:
    """Choix libre, sans validation ni « transfert » (RG-01). ``None`` : ne plus suivre."""
    if node is not None and not node.type.holds_registers:
        raise ApplicationError("Choisissez une paroisse.", code="not_a_parish")
    if node is not None and node.status == "supprime":
        raise ApplicationError("Cette paroisse n'existe plus.", code="parish_deleted")
    person.paroisse_suivie = node
    person.save(update_fields=["paroisse_suivie"])
    return person


# --- Retraits de capacités (EF-PER-09) ---------------------------------------------------


@transaction.atomic
def capability_override_create(
    *, actor: Any, diocese_node: Node, office_type: OfficeType, capability: Capability
) -> CapabilityOverride:
    if diocese_node.type.code != "diocese":
        raise ApplicationError("Un retrait de capacité se fait au niveau d'un diocèse.", code="override_not_diocese")
    if not authz.peut(actor, "plateforme.admin", None):
        raise PermissionDeniedError("Réservé à l'administration de la plateforme.")
    override, _ = CapabilityOverride.objects.get_or_create(
        diocese_node=diocese_node, office_type=office_type, capability=capability
    )
    audit_log(
        actor=actor,
        action="capacite.retrait",
        target=override,
        node=diocese_node,
        metadata={"office": office_type.code, "capacite": capability.code},
    )
    authz.invalidate_all()
    transaction.on_commit(authz.invalidate_all)
    return override


@transaction.atomic
def capability_override_delete(*, actor: Any, override: CapabilityOverride) -> None:
    if not authz.peut(actor, "plateforme.admin", None):
        raise PermissionDeniedError("Réservé à l'administration de la plateforme.")
    audit_log(actor=actor, action="capacite.retrait_annule", target=override, node=override.diocese_node)
    override.delete()
    authz.invalidate_all()
    transaction.on_commit(authz.invalidate_all)


def day_before(value: date) -> date:
    return value - timedelta(days=1)
