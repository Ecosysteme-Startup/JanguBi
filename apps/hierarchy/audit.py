"""Écriture du journal d'audit métier (EF-PER-11). Appelé par les services, jamais par les vues.

Adresse IP : celle passée explicitement, sinon celle de la requête en cours
(``apps.core.request_context``). Elle est **tronquée** avant écriture (IPv4 /24, IPv6 /48) :
le journal sert à la traçabilité d'un réseau, pas à identifier une machine (minimisation,
loi 2008-12 ; registre des traitements, T10).
"""

from typing import Any

from django.db import models

from apps.core.request_context import current_client_ip, ip_truncate
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
        ip=ip_truncate(ip or current_client_ip()),
    )
