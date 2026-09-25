"""Remplit la portée V1 (scope_node / scope_place) depuis les anciennes colonnes org.* (expand)."""

from django.db import migrations


def forwards(apps, schema_editor):
    Event = apps.get_model("agenda", "Event")
    Node = apps.get_model("hierarchy", "Node")
    Place = apps.get_model("hierarchy", "PlaceOfWorship")
    Church = apps.get_model("org", "Church")

    nodes = {(n.legacy_model, n.legacy_id): n.pk for n in Node.objects.exclude(legacy_model="").only("pk", "legacy_model", "legacy_id")}
    places = {p.legacy_id: p.pk for p in Place.objects.filter(legacy_id__isnull=False).only("pk", "legacy_id")}
    church_parish = dict(Church.objects.values_list("pk", "parish_id"))

    for event in Event.objects.filter(scope_node__isnull=True).exclude(scope_type="global").iterator():
        node_id = place_id = None
        if event.scope_type == "church" and event.scope_church_id:
            place_id = places.get(event.scope_church_id)
            node_id = nodes.get(("org.Parish", church_parish.get(event.scope_church_id)))
        elif event.scope_type == "parish" and event.scope_parish_id:
            node_id = nodes.get(("org.Parish", event.scope_parish_id))
        elif event.scope_type == "diocese" and event.scope_diocese_id:
            node_id = nodes.get(("org.Diocese", event.scope_diocese_id))
        if node_id:
            Event.objects.filter(pk=event.pk).update(scope_node_id=node_id, scope_place_id=place_id)


def backwards(apps, schema_editor):
    apps.get_model("agenda", "Event").objects.update(scope_node=None, scope_place=None)


class Migration(migrations.Migration):
    dependencies = [
        ("agenda", "0006_v1_node_scope"),
        ("hierarchy", "0003_migrate_org"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
