"""Insertion en masse par ``COPY`` (échelle grande : ~1 M de dons, ~5 M d'écoutes).

``copy_models`` prend des instances non sauvegardées et les écrit par ``COPY … FROM STDIN`` : les
valeurs par défaut Python des champs (``default=``) sont appliquées comme par ``save()``.
``copy_rows`` écrit des tuples bruts dans une table (tables non gérées : ``audio_play_event``).
"""

from __future__ import annotations

import datetime
import decimal
import io
import json
import uuid
from collections.abc import Iterable, Sequence
from typing import Any

from django.contrib.postgres.fields import ArrayField
from django.db import connection, models

CHUNK = 50_000


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def _array_literal(values: Sequence[Any]) -> str:
    items = []
    for v in values:
        if v is None:
            items.append("NULL")
        else:
            s = str(v).replace("\\", "\\\\").replace('"', '\\"')
            items.append(f'"{s}"')
    return "{" + ",".join(items) + "}"


def _format(value: Any) -> str:
    if value is None:
        return "\\N"
    if isinstance(value, bool):
        return "t" if value else "f"
    if isinstance(value, datetime.datetime | datetime.date | datetime.time):
        return value.isoformat()
    if isinstance(value, int | float | decimal.Decimal | uuid.UUID):
        return str(value)
    if isinstance(value, list | tuple):
        return _escape(_array_literal(value))
    if isinstance(value, dict):
        return _escape(json.dumps(value, ensure_ascii=False))
    return _escape(str(value))


def copy_rows(table: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> int:
    """``COPY table (columns) FROM STDIN`` par blocs de ``CHUNK`` lignes. Renvoie le nombre de lignes."""
    cols = ", ".join(f'"{c}"' for c in columns)
    sql = f'COPY "{table}" ({cols}) FROM STDIN'
    total = 0
    buf = io.StringIO()
    n = 0

    def flush() -> None:
        buf.seek(0)
        with connection.cursor() as cursor:
            cursor.cursor.copy_expert(sql, buf)  # psycopg2
        buf.seek(0)
        buf.truncate()

    for row in rows:
        buf.write("\t".join(_format(v) for v in row))
        buf.write("\n")
        n += 1
        if n >= CHUNK:
            flush()
            total += n
            n = 0
    if n:
        flush()
        total += n
    return total


def _field_value(field: models.Field, obj: models.Model) -> Any:
    value = field.pre_save(obj, add=True)
    if isinstance(field, models.JSONField):
        return None if value is None else json.dumps(value, ensure_ascii=False)
    if isinstance(field, ArrayField):
        return value
    if isinstance(field, models.ForeignKey):
        return value
    prepared = field.get_db_prep_save(value, connection)
    return prepared


def copy_models(model: type[models.Model], objs: Iterable[models.Model]) -> int:
    """Écrit des instances par ``COPY`` (clé primaire auto exclue si non renseignée)."""
    fields = [
        f
        for f in model._meta.concrete_fields
        if not (isinstance(f, models.AutoField | models.BigAutoField) and f.primary_key)
    ]
    columns = [f.column for f in fields]

    def rows() -> Iterable[list[Any]]:
        for obj in objs:
            yield [_field_value(f, obj) for f in fields]

    return copy_rows(model._meta.db_table, columns, rows())


def chunked(items: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]
