"""Capacités « dons » : catalogue fermé, offices, et règle « agrégats au-dessus de la paroisse »."""

import pytest

from apps.donations import access
from apps.hierarchy import authz
from apps.hierarchy.models import Capability, OfficeType

pytestmark = pytest.mark.django_db

DONS = {
    "dons.voir_fonds",
    "dons.gerer_fonds",
    "dons.saisir_quete",
    "dons.voir_donateurs",
    "dons.exporter",
    "dons.definir_quete_imperee",
}


def test_catalogue_contains_the_six_capabilities_and_the_parish_treasurer(world):
    assert DONS <= set(Capability.objects.values_list("code", flat=True))
    econome = OfficeType.objects.get(code="econome_paroissial")
    assert {c.code for c in econome.capabilities.all()} >= DONS - {"dons.definir_quete_imperee"}
    assert set(econome.appointed_by.values_list("code", flat=True)) == {"cure", "cure_in_solidum"}


@pytest.mark.parametrize(
    "who, capability, expected",
    [
        ("cure", "dons.voir_donateurs", True),
        ("econome", "dons.voir_donateurs", True),
        ("econome", "dons.exporter", True),
        ("secretaire", "dons.saisir_quete", True),
        ("secretaire", "dons.voir_fonds", True),
        ("secretaire", "dons.voir_donateurs", False),
        ("secretaire", "dons.gerer_fonds", False),
        ("fidele", "dons.voir_fonds", False),
        ("autre_cure", "dons.voir_fonds", False),  # autre paroisse
    ],
)
def test_parish_level_matrix(world, who, capability, expected):
    assert access.parish_level(getattr(world, who), capability, world.sd) is expected


def test_diocese_offices_get_aggregates_only(world):
    # L'évêque et l'économe diocésain héritent sur le sous-arbre, mais pas de lecture fine.
    for who in (world.eveque, world.econome_dio):
        assert authz.peut(who, "dons.definir_quete_imperee", world.dakar)
        assert not access.parish_level(who, "dons.voir_fonds", world.sd)
        assert not authz.peut(who, "dons.voir_donateurs", world.sd)
    assert not authz.a_la_capacite(world.doyen, "dons.voir_fonds")


def test_platform_has_no_donation_capability(world):
    assert not any(authz.a_la_capacite(world.platform, c) for c in DONS)


def test_parishes_for_lists_only_local_nominations(world):
    assert list(access.parishes_for(world.econome, "dons.voir_fonds")) == [world.sd]
    assert list(access.parishes_for(world.eveque, "dons.voir_fonds")) == []
