from datetime import date, time

import pytest
from django.db import IntegrityError, transaction

from apps.core.exceptions import ApplicationError
from apps.hierarchy import selectors
from apps.hierarchy.enums import NodeStatus
from apps.hierarchy.models import MassSchedule, Node, PlaceOfWorship
from apps.hierarchy.services import (
    node_create,
    node_update,
    place_update,
    schedule_exception_create,
    schedule_replace,
)
from apps.hierarchy.tests.factories import make_node, make_place, node_type

pytestmark = pytest.mark.django_db


# --- Invariants de l'arbre (EF-HIE-01) ---------------------------------------


def test_node_created_under_allowed_parent(tree):
    ceb = make_node("ceb", "CEB Saint-Paul", tree.saint_dominique)

    assert ceb.depth == tree.saint_dominique.depth + 1
    assert list(selectors.node_ancestors(node=ceb)) == [
        tree.province,
        tree.dakar,
        tree.doyenne,
        tree.saint_dominique,
    ]


def test_node_under_forbidden_parent_is_rejected(tree):
    with pytest.raises(ApplicationError) as exc:
        make_node("paroisse", "Paroisse dans une paroisse", tree.saint_dominique)

    assert exc.value.code == "parent_type_not_allowed"
    assert "ne peut pas être rattaché" in exc.value.message


def test_non_root_type_requires_a_parent(db):
    with pytest.raises(ApplicationError) as exc:
        make_node("paroisse", "Paroisse orpheline")
    assert exc.value.code == "parent_required"


def test_root_type_cannot_have_a_parent(tree):
    with pytest.raises(ApplicationError):
        make_node("province", "Sous-province", tree.dakar)


def test_parish_may_hang_directly_under_a_diocese(tree):
    parish = make_node("paroisse", "Paroisse sans doyenné", tree.thies)
    assert parish.depth == 3


def test_code_is_generated_and_unique(tree):
    a = make_node("ceb", "CEB Sainte-Anne", tree.saint_dominique)
    b = make_node("ceb", "CEB Sainte-Anne", tree.saint_dominique)
    assert a.code == "T-SD-CEB-SAINTE-ANNE"
    assert b.code == "T-SD-CEB-SAINTE-ANNE-2"


def test_explicit_code_must_be_unique(tree):
    with pytest.raises(ApplicationError) as exc:
        make_node("ceb", "CEB", tree.saint_dominique, code="T-SD")
    assert exc.value.code == "code_taken"


def test_node_update_changes_status_and_fields(tree):
    node = node_update(node=tree.sainte_therese, data={"status": NodeStatus.SUPPRIME, "city": "Dakar"})
    node.refresh_from_db()
    assert node.status == NodeStatus.SUPPRIME
    assert node.city == "Dakar"


def test_node_update_rejects_structural_fields(tree):
    with pytest.raises(ApplicationError) as exc:
        node_update(node=tree.sainte_therese, data={"type": node_type("ceb")})
    assert exc.value.code == "field_not_updatable"


def test_community_is_located_in_a_diocese_without_depending_on_it(tree):
    institut = make_node("institut", "Ordre des Prêcheurs")
    community = node_create(
        node_type=node_type("communaute"), name="Couvent de Dakar", parent=institut, located_in=tree.dakar
    )
    assert community.located_in == tree.dakar
    assert not selectors.node_subtree(node=tree.dakar).filter(pk=community.pk).exists()


# --- Sélecteurs (EF-HIE-03) ---------------------------------------------------


def test_children_and_ancestors_each_take_one_query(tree, django_assert_num_queries):
    with django_assert_num_queries(1):
        children = list(selectors.node_children(node=tree.doyenne))
    with django_assert_num_queries(1):
        ancestors = list(selectors.node_ancestors(node=tree.saint_dominique))

    assert {c.code for c in children} == {"T-SD", "T-ST"}
    assert [a.code for a in ancestors] == ["T-DAKP", "T-DAK", "T-PM"]


def test_node_list_filters(tree):
    assert set(selectors.node_list(filters={"type": "paroisse"}).values_list("code", flat=True)) == {
        "T-SD",
        "T-ST",
        "T-THI-CATH",
    }
    assert set(selectors.node_list(filters={"within": tree.dakar.pk, "type": "paroisse"}).values_list("code", flat=True)) == {
        "T-SD",
        "T-ST",
    }
    assert list(selectors.node_list(filters={"parent": tree.province.pk}).values_list("code", flat=True)) == [
        "T-DAK",
        "T-THI",
    ]
    assert list(selectors.node_list(filters={"q": "thérèse"}).values_list("code", flat=True)) == ["T-ST"]


def test_deleted_nodes_are_hidden_unless_requested(tree):
    node_update(node=tree.sainte_therese, data={"status": NodeStatus.SUPPRIME})
    assert "T-ST" not in selectors.node_list(filters={"type": "paroisse"}).values_list("code", flat=True)
    assert list(selectors.node_list(filters={"status": NodeStatus.SUPPRIME}).values_list("code", flat=True)) == ["T-ST"]


def test_ancestor_of_type(tree):
    assert selectors.node_ancestor_of_type(node=tree.saint_dominique, type_code="diocese") == tree.dakar
    assert selectors.node_ancestor_of_type(node=tree.dakar, type_code="diocese") == tree.dakar
    assert selectors.node_ancestor_of_type(node=tree.dakar, type_code="paroisse") is None


def test_unknown_node_raises_not_found(db):
    with pytest.raises(ApplicationError) as exc:
        selectors.node_get(node_id="00000000-0000-0000-0000-000000000000")
    assert exc.value.status_code == 404


# --- Lieux de culte (EF-HIE-04) ------------------------------------------------


def test_second_main_place_is_rejected(tree):
    make_place(tree.saint_dominique, "Église Saint-Dominique", is_main=True, kind="eglise_paroissiale")

    with pytest.raises(ApplicationError) as exc:
        make_place(tree.saint_dominique, "Autre église", is_main=True)
    assert exc.value.code == "main_place_exists"


def test_database_also_forbids_two_main_places(tree):
    make_place(tree.saint_dominique, "Église", is_main=True)
    with pytest.raises(IntegrityError), transaction.atomic():
        PlaceOfWorship.objects.create(node=tree.saint_dominique, name="Doublon", is_main=True)


def test_promoting_a_place_to_main_checks_the_other_places(tree):
    make_place(tree.saint_dominique, "Église", is_main=True)
    chapel = make_place(tree.saint_dominique, "Chapelle")
    with pytest.raises(ApplicationError):
        place_update(place=chapel, data={"is_main": True})


def test_main_place_can_be_edited(tree):
    main = make_place(tree.saint_dominique, "Église", is_main=True)
    main = place_update(place=main, data={"is_main": True, "name": "Église Saint-Dominique"})
    assert main.name == "Église Saint-Dominique"


# --- Horaires (EF-HIE-05) ------------------------------------------------------


def test_schedule_replace_swaps_the_whole_week(tree):
    place = make_place(tree.saint_dominique, "Église", is_main=True)
    schedule_replace(place=place, items=[{"weekday": 6, "start_time": time(9, 30)}])

    schedule_replace(
        place=place,
        items=[{"weekday": 6, "start_time": time(7, 30)}, {"weekday": 5, "start_time": time(16), "kind": "confession"}],
    )

    assert list(MassSchedule.objects.filter(place=place).values_list("weekday", "start_time")) == [
        (5, time(16)),
        (6, time(7, 30)),
    ]


def test_schedule_replace_is_atomic_on_invalid_item(tree):
    place = make_place(tree.saint_dominique, "Église", is_main=True)
    schedule_replace(place=place, items=[{"weekday": 6, "start_time": time(9, 30)}])

    with pytest.raises(ApplicationError) as exc:
        schedule_replace(
            place=place,
            items=[
                {"weekday": 0, "start_time": time(7)},
                {"weekday": 1, "start_time": time(8), "end_time": time(7)},
            ],
        )

    assert exc.value.extra["index"] == 1
    assert MassSchedule.objects.filter(place=place).count() == 1


def test_extra_schedule_needs_a_start_time(tree):
    place = make_place(tree.saint_dominique, "Église")
    with pytest.raises(ApplicationError) as exc:
        schedule_exception_create(place=place, date=date(2026, 10, 1), cancelled=False)
    assert exc.value.code == "exception_needs_time"


def test_node_week_merges_places_and_exceptions(tree):
    church = make_place(tree.saint_dominique, "Église", is_main=True)
    chapel = make_place(tree.saint_dominique, "Chapelle")
    schedule_replace(place=church, items=[{"weekday": 6, "start_time": time(9, 30)}])
    schedule_replace(place=chapel, items=[{"weekday": 6, "start_time": time(8)}])
    schedule_exception_create(place=chapel, date=date(2026, 10, 4), cancelled=True)

    places, week = selectors.node_week(node=tree.saint_dominique, start=date(2026, 9, 28))

    assert {p.name for p in places} == {"Église", "Chapelle"}
    assert [(o.place_id, o.start_time) for o in week] == [(church.pk, time(9, 30))]


def test_node_has_no_place_leak_between_nodes(tree):
    make_place(tree.sainte_therese, "Église Sainte-Thérèse", is_main=True)
    places, week = selectors.node_week(node=tree.saint_dominique, start=date(2026, 9, 28))
    assert places == [] and week == []


def test_tree_counts_children(tree):
    assert Node.objects.get(pk=tree.doyenne.pk).numchild == 2
