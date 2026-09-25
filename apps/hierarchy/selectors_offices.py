from datetime import date
from typing import Any

from django.contrib.auth import get_user_model
from django.db.models import Q, QuerySet

from apps.core.exceptions import NotFoundError
from apps.hierarchy import authz
from apps.hierarchy.enums import EtatDeVie, StatutVerification
from apps.hierarchy.models import AuditEvent, CapabilityOverride, Node, OfficeAssignment, OfficeType


def office_type_list() -> QuerySet[OfficeType]:
    return OfficeType.objects.prefetch_related("node_types", "appointed_by", "capabilities").order_by("label")


def office_type_get_by_code(*, code: str) -> OfficeType:
    try:
        return OfficeType.objects.get(code=code)
    except OfficeType.DoesNotExist as exc:
        raise NotFoundError(f"Office « {code} » inconnu.", {"office": code}) from exc


def assignment_list(*, actor: Any, filters: dict[str, Any] | None = None) -> QuerySet[OfficeAssignment]:
    """Nominations visibles par ``actor`` : celles des nœuds où il a ``offices.nommer``, plus les siennes."""
    filters = filters or {}
    allowed = authz.noeuds_autorises(actor, "offices.nommer")
    qs = OfficeAssignment.objects.filter(Q(node__in=allowed) | Q(person=actor)).select_related(
        "person", "office_type", "node", "node__type", "appointed_by"
    )
    if node_id := filters.get("node"):
        node = Node.objects.filter(pk=node_id).first()
        if node is None:
            raise NotFoundError("Nœud introuvable.", {"node_id": str(node_id)})
        qs = qs.filter(node__path__startswith=node.path)
    if person_id := filters.get("person"):
        qs = qs.filter(person_id=person_id)
    if status := filters.get("status"):
        qs = qs.filter(status=status)
    if office := filters.get("office"):
        qs = qs.filter(office_type__code=office)
    return qs.order_by("-start_date", "node__name")


def assignment_get(*, assignment_id: int) -> OfficeAssignment:
    try:
        return OfficeAssignment.objects.select_related("person", "office_type", "node", "node__type").get(
            pk=assignment_id
        )
    except OfficeAssignment.DoesNotExist as exc:
        raise NotFoundError("Nomination introuvable.", {"assignment_id": assignment_id}) from exc


def person_get(*, person_id: Any) -> Any:
    User = get_user_model()
    try:
        return User.objects.select_related("incardination_node", "institut_node", "paroisse_suivie").get(pk=person_id)
    except (User.DoesNotExist, ValueError) as exc:
        raise NotFoundError("Personne introuvable.", {"person_id": str(person_id)}) from exc


def person_get_by_email(*, email: str) -> Any:
    User = get_user_model()
    try:
        return User.objects.get(email__iexact=email.strip())
    except User.DoesNotExist as exc:
        raise NotFoundError(f"Aucun compte pour « {email} ».", {"email": email}) from exc


def verification_queue(*, actor: Any) -> QuerySet[Any]:
    """Déclarations en attente que ``actor`` peut vérifier (EF-PER-02)."""
    User = get_user_model()
    qs = (
        User.objects.filter(statut_verification=StatutVerification.DECLARE)
        .exclude(etat_de_vie=EtatDeVie.LAIC)
        .exclude(pk=actor.pk)
    )
    if authz.peut(actor, "personnes.verifier", None):
        return qs.select_related("incardination_node", "institut_node").order_by("email")
    allowed = authz.noeuds_autorises(actor, "personnes.verifier")
    return (
        qs.filter(Q(incardination_node__in=allowed) | Q(institut_node__in=allowed))
        .select_related("incardination_node", "institut_node")
        .order_by("email")
    )


def audit_list(*, actor: Any, filters: dict[str, Any] | None = None) -> QuerySet[AuditEvent]:
    """Journal visible : tout pour la plateforme, sinon les événements des nœuds où ``audit.voir`` (EF-DASH-04)."""
    filters = filters or {}
    qs = AuditEvent.objects.select_related("actor", "node")
    if not authz.peut(actor, "audit.voir", None):
        qs = qs.filter(node__in=authz.noeuds_autorises(actor, "audit.voir"))
    if node_id := filters.get("node"):
        node = Node.objects.filter(pk=node_id).first()
        qs = qs.filter(node__path__startswith=node.path) if node else qs.none()
    if actor_id := filters.get("actor"):
        qs = qs.filter(actor_id=actor_id)
    if action := filters.get("action"):
        qs = qs.filter(action__startswith=action)
    date_from: date | None = filters.get("date_from")
    date_to: date | None = filters.get("date_to")
    if date_from:
        qs = qs.filter(at__date__gte=date_from)
    if date_to:
        qs = qs.filter(at__date__lte=date_to)
    return qs.order_by("-at")


def capability_override_list() -> QuerySet[CapabilityOverride]:
    return CapabilityOverride.objects.select_related("diocese_node", "office_type", "capability").order_by(
        "diocese_node__name"
    )
