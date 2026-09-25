"""Remplit la portée V1 (scope_node / scope_place) depuis les anciennes colonnes org.* (expand).

Réversible : l'aller ne touche pas aux anciennes colonnes ; le retour vide les nouvelles.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    Article = apps.get_model("news", "Article")
    Node = apps.get_model("hierarchy", "Node")
    Place = apps.get_model("hierarchy", "PlaceOfWorship")
    Church = apps.get_model("org", "Church")

    nodes = {
        (n.legacy_model, n.legacy_id): n.pk
        for n in Node.objects.exclude(legacy_model="").only("pk", "legacy_model", "legacy_id")
    }
    places = {p.legacy_id: p.pk for p in Place.objects.filter(legacy_id__isnull=False).only("pk", "legacy_id")}
    church_parish = dict(Church.objects.values_list("pk", "parish_id"))

    for article in Article.objects.filter(scope_node__isnull=True).exclude(scope_type="global").iterator():
        node_id = place_id = None
        if article.scope_type == "church" and article.scope_church_id:
            place_id = places.get(article.scope_church_id)
            node_id = nodes.get(("org.Parish", church_parish.get(article.scope_church_id)))
        elif article.scope_type == "parish" and article.scope_parish_id:
            node_id = nodes.get(("org.Parish", article.scope_parish_id))
        elif article.scope_type == "diocese" and article.scope_diocese_id:
            node_id = nodes.get(("org.Diocese", article.scope_diocese_id))
        if node_id:
            Article.objects.filter(pk=article.pk).update(scope_node_id=node_id, scope_place_id=place_id)

    # Annonces datées d'un dimanche → « annonce du dimanche ».
    for article in Article.objects.filter(content_type="announcement", announcement_date__isnull=False).iterator():
        if article.announcement_date.weekday() == 6:
            Article.objects.filter(pk=article.pk).update(is_sunday_notice=True, sunday_date=article.announcement_date)


def backwards(apps, schema_editor):
    Article = apps.get_model("news", "Article")
    Article.objects.update(scope_node=None, scope_place=None, is_sunday_notice=False, sunday_date=None)


class Migration(migrations.Migration):
    dependencies = [
        ("news", "0009_v1_node_scope"),
        ("hierarchy", "0003_migrate_org"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
