"""Demandes existantes → modèle V1 (paroisse du sacrement en nœud, nouveaux statuts), aller-retour."""

import datetime

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

AFTER = [("documents", "0006_v1_backfill")]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    executor = MigrationExecutor(connection)
    return executor.loader.project_state(list(executor.loader.applied_migrations)).apps


@pytest.mark.django_db(transaction=True)
def test_legacy_requests_are_converted_both_ways():
    apps = _migrate([("documents", "0005_v1_node_pickup_register"), ("hierarchy", "0001_initial")])
    Province = apps.get_model("org", "Province")
    Diocese = apps.get_model("org", "Diocese")
    Parish = apps.get_model("org", "Parish")
    User = apps.get_model("users", "BaseUser")
    Request = apps.get_model("documents", "DocumentRequest")

    parish = Parish.objects.create(
        name="Saint-Dominique",
        diocese=Diocese.objects.create(name="Dakar", code="DAK", province=Province.objects.create(name="P", code="P")),
    )
    user = User.objects.create(email="f@test.sn", phone_number="+221770000009", role="fidele")
    common = {
        "requester": user,
        "document_type": "baptism",
        "reason": "personal",
        "requester_last_name": "N",
        "requester_first_names": "A",
        "date_of_birth": datetime.date(1990, 1, 1),
        "place_of_birth": "Dakar",
        "contact_phone": "1",
        "contact_email": "f@test.sn",
        "father_last_name": "N",
        "mother_last_name": "F",
        "parish_name": "Saint-Dominique",
        "diocese": "Dakar",
        "sacrament_approximate_date": "1990",
        "sacrament_location": "Dakar",
        "target_parish": parish,
    }
    validated = Request.objects.create(reference="R1", status="validated", **common)
    deposited = Request.objects.create(reference="R2", status="document_deposited", **common)
    rejected = Request.objects.create(reference="R3", status="rejected", **common)

    try:
        apps = _migrate([("hierarchy", "0003_migrate_org"), *AFTER])
        Request = apps.get_model("documents", "DocumentRequest")
        Node = apps.get_model("hierarchy", "Node")
        node = Node.objects.get(legacy_model="org.Parish", legacy_id=parish.pk)

        assert Request.objects.get(pk=validated.pk).status == "ready_for_pickup"
        assert Request.objects.get(pk=deposited.pk).status == "ready_for_pickup"
        converted = Request.objects.get(pk=rejected.pk)
        assert converted.target_node_id == node.pk and converted.closed_at is not None

        apps = _migrate([("documents", "0005_v1_node_pickup_register")])
        Request = apps.get_model("documents", "DocumentRequest")
        assert Request.objects.get(pk=validated.pk).status == "validated"
        assert Request.objects.filter(target_node__isnull=False).count() == 0
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
