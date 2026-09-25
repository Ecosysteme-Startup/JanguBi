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


# --- Personnes et nominations (L2) -------------------------------------------------------


def office(code: str):
    from apps.hierarchy.models import OfficeType
    from apps.hierarchy.seeding import offices_load

    if not OfficeType.objects.filter(code=code).exists():
        node_type("diocese")  # garantit les types de nœuds
        offices_load()
    return OfficeType.objects.get(code=code)


def person(email: str | None = None, *, ordre: str = "aucun", verified: bool = True, **kwargs):
    from apps.hierarchy.enums import DegreOrdre, EtatDeVie, StatutVerification
    from apps.users.tests.factories import BaseUserFactory

    etat = EtatDeVie.LAIC if ordre == DegreOrdre.AUCUN else EtatDeVie.CLERC
    fields = {
        "etat_de_vie": etat,
        "degre_ordre": ordre,
        "statut_verification": StatutVerification.VERIFIE if verified else StatutVerification.DECLARE,
        **kwargs,
    }
    if email:
        fields["email"] = email
    return BaseUserFactory.create(**fields)


def priest(email: str | None = None, **kwargs):
    return person(email, ordre="pretre", **kwargs)


def nominate(who, office_code: str, node: Node, **kwargs):
    """Nomination ACTIVE posée directement (mise en place de test, sans contrôle d'autorité)."""
    from datetime import date

    from apps.hierarchy import authz
    from apps.hierarchy.models import OfficeAssignment

    fields = {"start_date": date(2020, 1, 1), "status": "active", **kwargs}
    assignment = OfficeAssignment.objects.create(person=who, office_type=office(office_code), node=node, **fields)
    authz.invalidate_user(who.pk)
    return assignment
