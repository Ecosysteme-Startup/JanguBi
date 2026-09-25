"""Migration de données org → hierarchy, aller-retour (plan L1.6)."""

from decimal import Decimal

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

INITIAL = [("hierarchy", "0001_initial"), ("org", "0003_backfill_main_church")]
BEFORE = [("hierarchy", "0002_seed_node_types"), ("org", "0003_backfill_main_church")]
AFTER = [("hierarchy", "0003_migrate_org")]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


def _leaf():
    executor = MigrationExecutor(connection)
    return executor.loader.graph.leaf_nodes()


def _seed_org(apps):
    Province = apps.get_model("org", "Province")
    Diocese = apps.get_model("org", "Diocese")
    Deanery = apps.get_model("org", "Deanery")
    Parish = apps.get_model("org", "Parish")
    Church = apps.get_model("org", "Church")
    Order = apps.get_model("org", "ReligiousOrder")
    Community = apps.get_model("org", "ReligiousCommunity")

    province = Province.objects.create(name="Province de Dakar", code="DAKP")
    dakar = Diocese.objects.create(name="Archidiocèse de Dakar", code="DAK", province=province)
    thies = Diocese.objects.create(name="Diocèse de Thiès", code="THI", province=province)
    deanery = Deanery.objects.create(name="Plateau-Médina", diocese=dakar)
    with_deanery = Parish.objects.create(name="Saint-Dominique", diocese=dakar, deanery=deanery, city="Dakar")
    Parish.objects.create(name="Sainte-Thérèse", diocese=dakar, deanery=deanery)
    without_deanery = Parish.objects.create(name="Cathédrale de Thiès", diocese=thies, city="Thiès")
    Church.objects.create(
        parish=with_deanery, name="Église Saint-Dominique", church_type="paroissiale", is_main=True, latitude=Decimal("14.69")
    )
    Church.objects.create(parish=with_deanery, name="Chapelle UCAD", church_type="chapelle")
    Church.objects.create(parish=without_deanery, name="Succursale", church_type="succursale", is_active=False)
    order = Order.objects.create(name="Ordre des Prêcheurs", abbreviation="OP")
    Community.objects.create(name="Couvent de Dakar", order=order, diocese=dakar, parish=with_deanery)


@pytest.mark.django_db(transaction=True)
def test_org_data_is_migrated_both_ways():
    # Repartir de 0001 : un test transactionnel antérieur a pu vider les types
    # créés par la migration de données 0002 (flush en fin de test).
    _migrate(INITIAL)
    old_apps = _migrate(BEFORE)
    _seed_org(old_apps)

    new_apps = _migrate(AFTER)
    Node = new_apps.get_model("hierarchy", "Node")
    Place = new_apps.get_model("hierarchy", "PlaceOfWorship")

    try:
        by_name = {n.name: n for n in Node.objects.all()}
        province = by_name["Province de Dakar"]
        dakar = by_name["Archidiocèse de Dakar"]
        deanery = by_name["Plateau-Médina"]
        saint_dominique = by_name["Saint-Dominique"]
        thies_cathedral = by_name["Cathédrale de Thiès"]

        assert (province.code, province.depth, province.numchild) == ("DAKP", 1, 2)
        assert (dakar.code, dakar.type.code, dakar.path[:4]) == ("DAK", "diocese", province.path)
        assert saint_dominique.path.startswith(deanery.path) and saint_dominique.depth == 4
        assert saint_dominique.city == "Dakar" and saint_dominique.legacy_model == "org.Parish"
        assert thies_cathedral.path.startswith(by_name["Diocèse de Thiès"].path) and thies_cathedral.depth == 3
        assert deanery.numchild == 2

        places = {p.name: p for p in Place.objects.all()}
        assert places["Église Saint-Dominique"].kind == "eglise_paroissiale"
        assert places["Église Saint-Dominique"].is_main and places["Église Saint-Dominique"].lat == Decimal("14.69")
        assert places["Chapelle UCAD"].node_id == saint_dominique.pk
        assert places["Succursale"].kind == "succursale" and not places["Succursale"].is_active

        institut = by_name["Ordre des Prêcheurs (OP)"]
        community = by_name["Couvent de Dakar"]
        assert institut.type.code == "institut" and institut.depth == 1
        assert community.path.startswith(institut.path) and community.located_in_id == dakar.pk

        # Retour : les nœuds hérités disparaissent, org est intact.
        old_apps = _migrate(BEFORE)
        assert old_apps.get_model("hierarchy", "Node").objects.count() == 0
        assert old_apps.get_model("hierarchy", "PlaceOfWorship").objects.count() == 0
        assert old_apps.get_model("org", "Parish").objects.count() == 3

        # Re-aller : même résultat (idempotence de l'aller-retour).
        new_apps = _migrate(AFTER)
        assert new_apps.get_model("hierarchy", "Node").objects.count() == len(by_name)
    finally:
        _migrate(_leaf())
