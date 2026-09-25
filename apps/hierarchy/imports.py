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

from django.db import transaction

from apps.core.exceptions import ApplicationError
from apps.hierarchy.enums import NodeStatus, PlaceKind
from apps.hierarchy.models import Node, NodeType
from apps.hierarchy.services import node_create, place_create

NODE_COLUMNS = ("code", "type", "name", "parent_code")
NODE_OPTIONAL = ("status", "city", "address", "lat", "lng", "erected_at", "is_active_on_platform")
PLACE_COLUMNS = ("node_code", "name", "kind")
PLACE_OPTIONAL = ("is_main", "city", "address", "lat", "lng")
MAX_ROWS = 5000


@dataclass
class ImportLine:
    line: int
    status: str  # "ok" | "error"
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
        return sum(1 for line in self.lines if line.status == "ok")

    @property
    def applied(self) -> bool:
        return not self.dry_run and self.errors == 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "applied": self.applied,
            "valid": self.valid,
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


def _node_row(row: dict[str, str]) -> str:
    if not row["name"]:
        raise _RowError("Le nom est obligatoire.")
    try:
        node_type = NodeType.objects.get(code=row["type"])
    except NodeType.DoesNotExist as exc:
        raise _RowError(f"Type de nœud inconnu : « {row['type']} ».") from exc
    parent = None
    if row["parent_code"]:
        parent = Node.objects.select_related("type").filter(code=row["parent_code"]).first()
        if parent is None:
            raise _RowError(f"Parent introuvable : « {row['parent_code']} ».")
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


def _place_row(row: dict[str, str]) -> str:
    if not row["name"]:
        raise _RowError("Le nom est obligatoire.")
    node = Node.objects.filter(code=row["node_code"]).first()
    if node is None:
        raise _RowError(f"Nœud introuvable : « {row['node_code']} ».")
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


def _run(*, rows: list[dict[str, str]], handler: Callable[[dict[str, str]], str], dry_run: bool) -> ImportReport:
    report = ImportReport(dry_run=dry_run)
    with transaction.atomic():
        for index, row in enumerate(rows, start=2):  # ligne 1 = en-tête
            try:
                with transaction.atomic():
                    code = handler(row)
            except (_RowError, ApplicationError) as exc:
                message = exc.message if isinstance(exc, ApplicationError) else str(exc)
                report.lines.append(ImportLine(line=index, status="error", message=message))
            else:
                report.lines.append(ImportLine(line=index, status="ok", message="Valide", code=code))
        if dry_run or report.errors:
            transaction.set_rollback(True)
    return report


def nodes_import_csv(*, content: str, dry_run: bool = True) -> ImportReport:
    """Colonnes : code, type, name, parent_code (+ status, city, address, lat, lng, erected_at,
    is_active_on_platform). ``code`` vide = code généré."""
    return _run(rows=_read_rows(content=content, required=NODE_COLUMNS), handler=_node_row, dry_run=dry_run)


def places_import_csv(*, content: str, dry_run: bool = True) -> ImportReport:
    """Colonnes : node_code, name, kind (+ is_main, city, address, lat, lng)."""
    return _run(rows=_read_rows(content=content, required=PLACE_COLUMNS), handler=_place_row, dry_run=dry_run)
