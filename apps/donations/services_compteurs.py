"""Équipe des compteurs de quête d'une paroisse (lot V1-routes, G08).

Même droit que la saisie des quêtes (``dons.saisir_quete`` par une nomination sur la paroisse
même). Journalisé. Un compteur retiré est désactivé, jamais effacé.
"""

from typing import Any

from django.db import IntegrityError, transaction

from apps.core.exceptions import ApplicationError
from apps.donations import access
from apps.donations.models import CollectionCounter
from apps.hierarchy.audit import audit_log
from apps.hierarchy.models import Node


def _name_clean(name: str) -> str:
    clean = " ".join((name or "").split())
    if not clean:
        raise ApplicationError("Indiquez le nom du compteur.", code="counter_name_required")
    return clean[:120]


def _save(counter: CollectionCounter, **kwargs: Any) -> None:
    try:
        with transaction.atomic():
            counter.save(**kwargs)
    except IntegrityError as exc:
        raise ApplicationError("Ce compteur fait déjà partie de l'équipe.", code="counter_duplicate") from exc


@transaction.atomic
def counter_add(*, actor: Any, node: Node, name: str) -> CollectionCounter:
    access.require_parish_level(actor, "dons.saisir_quete", node)
    counter = CollectionCounter(node=node, name=_name_clean(name), created_by=actor)
    _save(counter)
    audit_log(actor=actor, action="dons.compteur_ajout", target=counter, node=node)
    return counter


@transaction.atomic
def counter_rename(*, actor: Any, counter: CollectionCounter, name: str) -> CollectionCounter:
    access.require_parish_level(actor, "dons.saisir_quete", counter.node)
    if not counter.is_active:
        raise ApplicationError("Ce compteur a été retiré de l'équipe.", code="counter_inactive")
    counter.name = _name_clean(name)
    _save(counter, update_fields=["name", "updated_at"])
    audit_log(actor=actor, action="dons.compteur_modification", target=counter, node=counter.node)
    return counter


@transaction.atomic
def counter_remove(*, actor: Any, counter: CollectionCounter) -> CollectionCounter:
    access.require_parish_level(actor, "dons.saisir_quete", counter.node)
    if counter.is_active:
        counter.is_active = False
        counter.save(update_fields=["is_active", "updated_at"])
        audit_log(actor=actor, action="dons.compteur_retrait", target=counter, node=counter.node)
    return counter
