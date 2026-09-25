"""Écriture du journal d'audit métier (EF-PER-11). Appelé par les services, jamais par les vues."""

from typing import Any

from django.db import models

from apps.hierarchy.models import AuditEvent, Node


def audit_log(
    *,
    actor: Any,
    action: str,
    target: models.Model,
    node: Node | None = None,
    metadata: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditEvent:
    return AuditEvent.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        target_type=target._meta.label,
        target_id=str(target.pk),
        node=node,
        metadata=metadata or {},
        ip=ip,
    )
