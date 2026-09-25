"""Construction d'arbres de test. Les types de nœuds viennent de la migration 0002."""

from apps.hierarchy.models import Node, NodeType, PlaceOfWorship
from apps.hierarchy.seeding import node_types_load
from apps.hierarchy.services import node_create, place_create


def node_type(code: str) -> NodeType:
    # Les types viennent d'une migration de données ; un test transactionnel (flush)
    # les efface : on les recharge au besoin.
    if not NodeType.objects.filter(code=code).exists():
        node_types_load(profile="senegal")
    return NodeType.objects.get(code=code)


def make_node(type_code: str, name: str, parent: Node | None = None, **kwargs) -> Node:
    return node_create(node_type=node_type(type_code), name=name, parent=parent, **kwargs)


def make_place(node: Node, name: str = "Église", **kwargs) -> PlaceOfWorship:
    return place_create(node=node, name=name, **kwargs)


class Tree:
    """Province → 2 diocèses → doyenné → 2 paroisses (Dakar) ; 1 paroisse (Thiès)."""

    def __init__(self) -> None:
        self.province = make_node("province", "Province de Dakar", code="T-DAKP")
        self.dakar = make_node("diocese", "Archidiocèse de Dakar", self.province, code="T-DAK")
        self.thies = make_node("diocese", "Diocèse de Thiès", self.province, code="T-THI")
        self.doyenne = make_node("doyenne", "Doyenné Plateau-Médina", self.dakar, code="T-PM")
        self.saint_dominique = make_node("paroisse", "Saint-Dominique", self.doyenne, code="T-SD")
        self.sainte_therese = make_node("paroisse", "Sainte-Thérèse", self.doyenne, code="T-ST")
        self.thies_parish = make_node("paroisse", "Cathédrale de Thiès", self.thies, code="T-THI-CATH")
        self.refresh()

    def refresh(self) -> None:
        for name, value in list(vars(self).items()):
            if isinstance(value, Node):
                setattr(self, name, Node.objects.get(pk=value.pk))
