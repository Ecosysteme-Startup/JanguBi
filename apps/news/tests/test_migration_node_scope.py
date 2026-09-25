"""Remplissage de la portée V1 des annonces et événements depuis org.* (aller-retour)."""

import datetime

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [
    ("news", "0009_v1_node_scope"),
    ("agenda", "0006_v1_node_scope"),
    ("hierarchy", "0003_migrate_org"),
    ("hierarchy", "0001_initial"),
]
AFTER = [("news", "0010_v1_backfill_node_scope"), ("agenda", "0007_v1_backfill_node_scope")]


def _migrate(targets):
    """Migre, puis renvoie l'état historique de TOUTES les migrations appliquées
    (sinon les apps non ciblées, comme users, seraient vues à leur état initial)."""
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    executor = MigrationExecutor(connection)
    return executor.loader.project_state(list(executor.loader.applied_migrations)).apps


@pytest.mark.django_db(transaction=True)
def test_legacy_scopes_become_nodes_both_ways():
    # hierarchy à 0001 puis 0003 : repart d'une base où la migration org → nœuds s'applique aux données ci-dessous.
    apps = _migrate([("news", "0009_v1_node_scope"), ("agenda", "0006_v1_node_scope"), ("hierarchy", "0001_initial")])
    Province = apps.get_model("org", "Province")
    Diocese = apps.get_model("org", "Diocese")
    Parish = apps.get_model("org", "Parish")
    Church = apps.get_model("org", "Church")
    User = apps.get_model("users", "BaseUser")
    Category = apps.get_model("news", "ArticleCategory")
    Article = apps.get_model("news", "Article")
    Event = apps.get_model("agenda", "Event")

    diocese = Diocese.objects.create(name="Dakar", code="DAK", province=Province.objects.create(name="P", code="DAKP"))
    parish = Parish.objects.create(name="Saint-Dominique", diocese=diocese)
    church = Church.objects.create(parish=parish, name="Chapelle", is_main=False)
    author = User.objects.create(
        email="a@test.sn",
        phone_number="+221770000001",
        role="fidele",
    )
    category = Category.objects.create(name="C", slug="c")
    common = {"author": author, "category": category, "content": "x"}
    by_parish = Article.objects.create(title="P", slug="p", scope_type="parish", scope_parish=parish, **common)
    by_church = Article.objects.create(title="E", slug="e", scope_type="church", scope_church=church, **common)
    by_diocese = Article.objects.create(title="D", slug="d", scope_type="diocese", scope_diocese=diocese, **common)
    sunday = Article.objects.create(
        title="S", slug="s", content_type="announcement", announcement_date=datetime.date(2026, 9, 27), **common
    )
    now = datetime.datetime(2026, 10, 1, 10, tzinfo=datetime.UTC)
    event = Event.objects.create(title="Ev", start_at=now, end_at=now, scope_type="church", scope_church=church)

    try:
        apps = _migrate([("hierarchy", "0003_migrate_org"), *AFTER])
        Article = apps.get_model("news", "Article")
        Node = apps.get_model("hierarchy", "Node")
        parish_node = Node.objects.get(legacy_model="org.Parish", legacy_id=parish.pk)

        assert Article.objects.get(pk=by_parish.pk).scope_node_id == parish_node.pk
        church_article = Article.objects.get(pk=by_church.pk)
        assert church_article.scope_node_id == parish_node.pk and church_article.scope_place_id is not None
        assert Article.objects.get(pk=by_diocese.pk).scope_node.legacy_model == "org.Diocese"
        s = Article.objects.get(pk=sunday.pk)
        assert s.is_sunday_notice and s.sunday_date == datetime.date(2026, 9, 27)
        assert apps.get_model("agenda", "Event").objects.get(pk=event.pk).scope_node_id == parish_node.pk

        apps = _migrate([("news", "0009_v1_node_scope"), ("agenda", "0006_v1_node_scope")])
        assert apps.get_model("news", "Article").objects.filter(scope_node__isnull=False).count() == 0
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
