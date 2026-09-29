"""Événements temps réel des tableaux de bord des dons (flux SSE ``staff/dons/flux/``).

Branchement sans toucher aux services des dons : récepteurs ``post_save`` publiés après la
transaction (``transaction.on_commit``). Événements :

- ``dons.operation`` (flux de la paroisse seulement) : un don confirmé ou remboursé, une
  quête saisie ou rejetée. Ni montant ni nom : le client recharge la liste des opérations,
  qui applique ses propres règles (noms masqués sans ``dons.voir_donateurs``).
- ``dons.synthese_invalidee`` (paroisse et diocèse) : la synthèse a changé, à recharger.
  Côté diocèse, rien n'indique la paroisse concernée (agrégats seulement, RG-11).

Une quête validée crée un don confirmé : c'est ce don qui produit l'événement.
"""

from functools import partial
from typing import Any

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from apps.core.exceptions import ApplicationError, PermissionDeniedError
from apps.donations import access
from apps.donations.enums import DIOCESE_TYPES, CashCollectionStatus, DonationStatus
from apps.donations.models import CashCollection, Donation
from apps.hierarchy import authz
from apps.hierarchy.models import Node
from apps.hierarchy.selectors import node_ancestors
from apps.realtime.sse import sse_publish

EVENT_OPERATION = "dons.operation"
EVENT_SUMMARY = "dons.synthese_invalidee"
DONATION_EVENT_STATUSES = frozenset({DonationStatus.CONFIRME, DonationStatus.REMBOURSE})
CASH_EVENT_STATUSES = frozenset({CashCollectionStatus.SAISIE, CashCollectionStatus.REJETEE})
# Lecture des agrégats diocésains : la capacité dédiée si le catalogue la connaît (lot A2),
# sinon celle qui suit déjà les quêtes impérées du diocèse.
DIOCESE_CAPABILITIES = ("dons.voir_agregats", "dons.definir_quete_imperee")


def stream_for(node_id: Any) -> str:
    return f"dons.{node_id}"


def _diocese_id(parish: Node) -> Any:
    return node_ancestors(node=parish).filter(type__code__in=DIOCESE_TYPES).values_list("pk", flat=True).first()


def _month(at: Any) -> str:
    return timezone.localtime(at or timezone.now()).strftime("%Y-%m")


def dons_publish(*, parish_id: Any, diocese_id: Any, operation: dict[str, Any], fund_id: Any, month: str) -> None:
    """Publie l'opération et l'invalidation sur le flux de la paroisse, puis l'invalidation
    (anonyme) sur le flux du diocèse."""
    sse_publish(stream=stream_for(parish_id), event=EVENT_OPERATION, data=operation)
    sse_publish(
        stream=stream_for(parish_id),
        event=EVENT_SUMMARY,
        data={"node_id": str(parish_id), "fund_id": str(fund_id), "month": month},
    )
    if diocese_id is not None:
        sse_publish(
            stream=stream_for(diocese_id), event=EVENT_SUMMARY, data={"node_id": str(diocese_id), "month": month}
        )


def _status_touched(created: bool, update_fields: Any) -> bool:
    return created or update_fields is None or "status" in update_fields


@receiver(post_save, sender=Donation, dispatch_uid="realtime_dons_donation")
def donation_saved(sender: Any, instance: Donation, created: bool, update_fields: Any = None, **kwargs: Any) -> None:
    if kwargs.get("raw") or instance.status not in DONATION_EVENT_STATUSES:
        return
    if not _status_touched(created, update_fields):
        return
    parish = Node.objects.filter(donation_funds__pk=instance.fund_id).first()
    if parish is None:
        return
    at = instance.confirmed_at if instance.status == DonationStatus.CONFIRME else instance.status_changed_at
    operation = {
        "kind": "don",
        "id": str(instance.pk),
        "fund_id": str(instance.fund_id),
        "channel": instance.channel,
        "status": instance.status,
        "at": (at or timezone.now()).isoformat(),
    }
    transaction.on_commit(
        partial(
            dons_publish,
            parish_id=parish.pk,
            diocese_id=_diocese_id(parish),
            operation=operation,
            fund_id=instance.fund_id,
            month=_month(at),
        )
    )


@receiver(post_save, sender=CashCollection, dispatch_uid="realtime_dons_cash")
def cash_collection_saved(
    sender: Any, instance: CashCollection, created: bool, update_fields: Any = None, **kwargs: Any
) -> None:
    if kwargs.get("raw") or instance.status not in CASH_EVENT_STATUSES:
        return
    if not _status_touched(created, update_fields):
        return
    parish = Node.objects.filter(pk=instance.node_id).first()
    if parish is None:
        return
    operation = {
        "kind": "quete",
        "id": str(instance.pk),
        "fund_id": str(instance.fund_id),
        "channel": "especes",
        "status": instance.status,
        "at": timezone.now().isoformat(),
    }
    transaction.on_commit(
        partial(
            dons_publish,
            parish_id=parish.pk,
            diocese_id=_diocese_id(parish),
            operation=operation,
            fund_id=instance.fund_id,
            month=instance.mass_date.strftime("%Y-%m"),
        )
    )


# --- Droits du flux ------------------------------------------------------------------------------


def dons_flux_check(*, user: Any, node: Node) -> None:
    """Paroisse : ``dons.voir_fonds`` par une nomination sur la paroisse même (comme la synthèse).
    Diocèse : capacité d'agrégats diocésains. MFA exigée dans les deux cas."""
    if access.is_parish(node):
        access.require_parish_level(user, "dons.voir_fonds", node)
        return
    if access.is_diocese(node):
        known = [c for c in DIOCESE_CAPABILITIES if c in authz.CAPABILITY_CODES]
        if not any(authz.peut(user, c, node) for c in known):
            raise PermissionDeniedError("Vous n'avez pas ce droit sur ce diocèse.", code="dons_forbidden")
        authz.mfa_check(user)
        return
    raise ApplicationError("Le flux existe pour une paroisse ou un diocèse.", code="invalid_node")


def dons_resync(node_id: Any) -> tuple[str, dict[str, Any]]:
    """Événement envoyé quand la reprise est impossible : tout recharger."""
    return EVENT_SUMMARY, {"node_id": str(node_id), "month": _month(None), "resync": True}
