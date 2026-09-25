"""Import CSV des nœuds et des lieux de culte (EF-HIE-06).

Toutes les lignes sont appliquées dans une transaction. Elle est annulée si
``dry_run`` est vrai **ou** si une ligne est en erreur : la simulation est donc
exacte (un parent créé plus haut dans le fichier est bien vu par les lignes
suivantes) et l'application est tout ou rien.
"""

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import IntegrityError, transaction

from apps.core.exceptions import ApplicationError
from apps.hierarchy.enums import NodeStatus, PlaceKind
from apps.hierarchy.models import Node, NodeType, OfficeAssignment, OfficeType
from apps.hierarchy.services import node_create, place_create

NODE_COLUMNS = ("code", "type", "name", "parent_code")
NODE_OPTIONAL = ("status", "city", "address", "lat", "lng", "erected_at", "is_active_on_platform")
PLACE_COLUMNS = ("node_code", "name", "kind")
PLACE_OPTIONAL = ("is_main", "city", "address", "lat", "lng")
MAX_ROWS = 5000


@dataclass
class ImportLine:
    line: int
    status: str  # "ok" | "warning" | "error"
    message: str
    code: str = ""


@dataclass
class ImportReport:
    dry_run: bool
    lines: list[ImportLine] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(1 for line in self.lines if line.status == "error")

    @property
    def valid(self) -> int:
        return sum(1 for line in self.lines if line.status != "error")

    @property
    def warnings(self) -> int:
        return sum(1 for line in self.lines if line.status == "warning")

    @property
    def applied(self) -> bool:
        return not self.dry_run and self.errors == 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "applied": self.applied,
            "valid": self.valid,
            "warnings": self.warnings,
            "errors": self.errors,
            "lines": [line.__dict__ for line in self.lines],
        }


class _RowError(Exception):
    pass


def _read_rows(*, content: str, required: tuple[str, ...]) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(content.lstrip("﻿")))
    headers = {h.strip() for h in (reader.fieldnames or [])}
    missing = [c for c in required if c not in headers]
    if missing:
        raise ApplicationError("Colonnes manquantes dans le CSV.", {"missing": missing}, code="csv_missing_columns")
    rows = [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]
    if len(rows) > MAX_ROWS:
        raise ApplicationError(f"Le fichier dépasse {MAX_ROWS} lignes.", code="csv_too_large")
    return rows


def _decimal(value: str, name: str) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise _RowError(f"{name} invalide : « {value} ».") from exc


def _bool(value: str) -> bool:
    return value.lower() in {"1", "true", "vrai", "oui", "yes", "x"}


def _date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise _RowError(f"Date invalide : « {value} » (attendu AAAA-MM-JJ).") from exc


def _structure_check(actor: Any, node: Node | None) -> None:
    from apps.hierarchy.authz import peut

    if actor is not None and not peut(actor, "structure.gerer", node):
        target = node.name if node is not None else "la racine"
        raise _RowError(f"Vous ne pouvez pas modifier la structure sous « {target} ».")


def _node_row(row: dict[str, str], actor: Any = None) -> str:
    if not row["name"]:
        raise _RowError("Le nom est obligatoire.")
    try:
        node_type = NodeType.objects.prefetch_related("allowed_parent_types").get(code=row["type"])
    except NodeType.DoesNotExist as exc:
        raise _RowError(f"Type de nœud inconnu : « {row['type']} ».") from exc
    parent = None
    if row["parent_code"]:
        parent = Node.objects.select_related("type").filter(code=row["parent_code"]).first()
        if parent is None:
            raise _RowError(f"Parent introuvable : « {row['parent_code']} ».")
    _structure_check(actor, parent)
    status = row.get("status") or NodeStatus.ERIGE
    if status not in NodeStatus.values:
        raise _RowError(f"Statut inconnu : « {status} ».")
    node = node_create(
        node_type=node_type,
        name=row["name"],
        parent=parent,
        code=row["code"] or None,
        status=status,
        city=row.get("city", ""),
        address=row.get("address", ""),
        lat=_decimal(row.get("lat", ""), "Latitude"),
        lng=_decimal(row.get("lng", ""), "Longitude"),
        erected_at=_date(row.get("erected_at", "")),
        is_active_on_platform=_bool(row.get("is_active_on_platform", "")),
    )
    return node.code


def _place_row(row: dict[str, str], actor: Any = None) -> str:
    if not row["name"]:
        raise _RowError("Le nom est obligatoire.")
    node = Node.objects.filter(code=row["node_code"]).first()
    if node is None:
        raise _RowError(f"Nœud introuvable : « {row['node_code']} ».")
    _structure_check(actor, node)
    kind = row["kind"] or PlaceKind.CHAPELLE
    if kind not in PlaceKind.values:
        raise _RowError(f"Type de lieu inconnu : « {kind} ».")
    place = place_create(
        node=node,
        name=row["name"],
        kind=kind,
        is_main=_bool(row.get("is_main", "")),
        city=row.get("city", ""),
        address=row.get("address", ""),
        lat=_decimal(row.get("lat", ""), "Latitude"),
        lng=_decimal(row.get("lng", ""), "Longitude"),
    )
    return node.code + " / " + place.name


# Un gestionnaire de ligne renvoie un code, ou (code, avertissement).
RowResult = str | tuple[str, str]


def _run(*, rows: list[dict[str, str]], handler: Callable[[dict[str, str]], RowResult], dry_run: bool) -> ImportReport:
    report = ImportReport(dry_run=dry_run)
    with transaction.atomic():
        for index, row in enumerate(rows, start=2):  # ligne 1 = en-tête
            try:
                with transaction.atomic():
                    code = handler(row)
            except (_RowError, ApplicationError, IntegrityError) as exc:
                if isinstance(exc, ApplicationError):
                    message = exc.message
                elif isinstance(exc, IntegrityError):
                    message = "Doublon ou contrainte violée (code déjà utilisé ?)."
                else:
                    message = str(exc)
                report.lines.append(ImportLine(line=index, status="error", message=message))
            else:
                if isinstance(code, tuple):
                    code, warning = code
                    report.lines.append(ImportLine(line=index, status="warning", message=warning, code=code))
                else:
                    report.lines.append(ImportLine(line=index, status="ok", message="Valide", code=code))
        if dry_run or report.errors:
            transaction.set_rollback(True)
    return report


def nodes_import_csv(*, content: str, dry_run: bool = True, actor: Any = None) -> ImportReport:
    """Colonnes : code, type, name, parent_code (+ status, city, address, lat, lng, erected_at,
    is_active_on_platform). ``code`` vide = code généré. Avec ``actor`` : ``structure.gerer``
    est vérifié ligne par ligne sur le parent."""
    rows = _read_rows(content=content, required=NODE_COLUMNS)
    return _run(rows=rows, handler=lambda row: _node_row(row, actor), dry_run=dry_run)


def places_import_csv(*, content: str, dry_run: bool = True, actor: Any = None) -> ImportReport:
    """Colonnes : node_code, name, kind (+ is_main, city, address, lat, lng)."""
    rows = _read_rows(content=content, required=PLACE_COLUMNS)
    return _run(rows=rows, handler=lambda row: _place_row(row, actor), dry_run=dry_run)


# --- Mouvement annuel des affectations (EF-PER-07) ---------------------------------------

ASSIGNMENT_COLUMNS = ("action", "email", "office", "node_code")
ASSIGNMENT_OPTIONAL = ("start_date", "end_date", "decree_ref")


def assignments_import_csv(
    *, actor: Any, content: str, effective_date: date, dry_run: bool = True
) -> ImportReport:
    """Colonnes : action (``nommer`` | ``terminer``), email, office, node_code (+ start_date,
    end_date, decree_ref). Date par défaut : ``effective_date``. Pour un office à titulaire
    unique, le titulaire en place est terminé la veille (avertissement)."""
    from apps.hierarchy.selectors_offices import person_get_by_email
    from apps.hierarchy.services_offices import (
        assignment_create,
        assignment_terminate,
        day_before,
        previous_holder_end,
    )

    def handle(row: dict[str, str]) -> RowResult:
        action = row["action"].lower()
        if action not in {"nommer", "terminer"}:
            raise _RowError(f"Action inconnue : « {row['action']} » (nommer ou terminer).")
        try:
            person = person_get_by_email(email=row["email"])
        except ApplicationError as exc:
            raise _RowError(exc.message) from exc
        office = OfficeType.objects.filter(code=row["office"]).first()
        if office is None:
            raise _RowError(f"Office inconnu : « {row['office']} ».")
        node = Node.objects.select_related("type").filter(code=row["node_code"]).first()
        if node is None:
            raise _RowError(f"Nœud introuvable : « {row['node_code']} ».")
        start = _date(row.get("start_date", "")) or effective_date
        label = f"{person.email} — {office.code} — {node.code}"

        if action == "terminer":
            current = OfficeAssignment.objects.filter(
                person=person, office_type=office, node=node, status__in=["proposee", "active"]
            ).first()
            if current is None:
                raise _RowError("Aucune nomination en cours à terminer.")
            assignment_terminate(actor=actor, assignment=current, end_date=_date(row.get("end_date", "")) or start)
            return label

        warning = ""
        for holder in previous_holder_end(office_type=office, node=node, start=start):
            assignment_terminate(actor=actor, assignment=holder, end_date=max(day_before(start), holder.start_date))
            warning = f"Le titulaire précédent ({holder.person.email}) est terminé au {day_before(start):%d/%m/%Y}."
        assignment_create(
            actor=actor,
            person=person,
            office_type=office,
            node=node,
            start_date=start,
            end_date=_date(row.get("end_date", "")),
            decree_ref=row.get("decree_ref", ""),
        )
        return (label, warning) if warning else label

    return _run(rows=_read_rows(content=content, required=ASSIGNMENT_COLUMNS), handler=handle, dry_run=dry_run)
