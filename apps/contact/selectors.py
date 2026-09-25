from uuid import UUID

from apps.hierarchy.models import Node

DIOCESE_TYPE = "diocese"


def diocese_get_or_none(*, node_id: UUID) -> Node | None:
    return Node.objects.filter(pk=node_id, type__code=DIOCESE_TYPE).first()
