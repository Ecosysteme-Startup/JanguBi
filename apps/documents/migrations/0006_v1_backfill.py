"""Demandes existantes → modèle V1 : paroisse du sacrement en nœud, statuts du nouveau cycle.

- target_node depuis target_parish (via hierarchy legacy_model/legacy_id) ;
- validated et document_deposited → ready_for_pickup (plan L5 ; ADR-009 : plus de dépôt numérique) ;
- closed_at posé sur les demandes déjà rejetées.

Retour : ready_for_pickup redevient validated (le détail validated / deposited n'est pas
conservé : acceptable, les deux signifiaient « traitée par la paroisse ») ; target_node vidé.
"""

from django.db import migrations
from django.db.models import F


def forwards(apps, schema_editor):
    DocumentRequest = apps.get_model("documents", "DocumentRequest")
    Node = apps.get_model("hierarchy", "Node")
    parishes = dict(Node.objects.filter(legacy_model="org.Parish").values_list("legacy_id", "pk"))

    for request in DocumentRequest.objects.filter(target_node__isnull=True, target_parish__isnull=False).only(
        "pk", "target_parish_id"
    ):
        node_id = parishes.get(request.target_parish_id)
        if node_id:
            DocumentRequest.objects.filter(pk=request.pk).update(target_node_id=node_id)

    DocumentRequest.objects.filter(status__in=["validated", "document_deposited"]).update(status="ready_for_pickup")
    DocumentRequest.objects.filter(status="rejected", closed_at__isnull=True).update(closed_at=F("updated_at"))


def backwards(apps, schema_editor):
    DocumentRequest = apps.get_model("documents", "DocumentRequest")
    DocumentRequest.objects.filter(status="ready_for_pickup").update(status="validated")
    # Seules les demandes venues d'org perdent leur nœud ; celles créées en V1 (sans
    # target_parish) le gardent, sinon la file de la paroisse serait perdue au retour.
    DocumentRequest.objects.filter(target_parish__isnull=False).update(target_node=None)


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0005_v1_node_pickup_register"),
        ("hierarchy", "0003_migrate_org"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
