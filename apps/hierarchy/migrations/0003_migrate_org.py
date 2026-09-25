"""Migration des données org.* vers l'arbre des juridictions (SRS §5.4, ADR-002).

Les modèles historiques n'exposent pas les méthodes treebeard : le chemin
matérialisé (pas de 4, base 36) est donc calculé ici. Chaque nœud garde
``legacy_model`` + ``legacy_id`` ; la migration inverse supprime les nœuds
hérités, leur sous-arbre et leurs lieux de culte. ``org`` n'est pas modifié.
"""

from django.db import migrations
from treebeard.numconv import NumConv

STEPLEN = 4
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_conv = NumConv(len(ALPHABET), ALPHABET)

CHURCH_KIND = {
    "paroissiale": "eglise_paroissiale",
    "succursale": "succursale",
    "chapelle": "chapelle",
    "station": "station",
}


class _Tree:
    def __init__(self, Node):
        self.Node = Node

    def _next_path(self, parent):
        siblings = self.Node.objects.filter(depth=(parent.depth + 1) if parent else 1)
        if parent is not None:
            siblings = siblings.filter(path__startswith=parent.path)
        last = siblings.order_by("-path").values_list("path", flat=True).first()
        index = _conv.str2int(last[-STEPLEN:]) + 1 if last else 1
        return (parent.path if parent else "") + _conv.int2str(index).rjust(STEPLEN, "0")

    def add(self, *, parent, **fields):
        node = self.Node.objects.create(
            path=self._next_path(parent),
            depth=(parent.depth + 1) if parent else 1,
            numchild=0,
            **fields,
        )
        if parent is not None:
            parent.numchild += 1
            parent.save(update_fields=["numchild"])
        return node


def _unique_code(Node, wanted):
    code, suffix = wanted[:64], 2
    while Node.objects.filter(code=code).exists():
        code = f"{wanted[:58]}-{suffix}"
        suffix += 1
    return code


def forwards(apps, schema_editor):
    Node = apps.get_model("hierarchy", "Node")
    NodeType = apps.get_model("hierarchy", "NodeType")
    Place = apps.get_model("hierarchy", "PlaceOfWorship")
    Province = apps.get_model("org", "Province")
    Diocese = apps.get_model("org", "Diocese")
    Deanery = apps.get_model("org", "Deanery")
    Parish = apps.get_model("org", "Parish")
    Church = apps.get_model("org", "Church")
    ReligiousOrder = apps.get_model("org", "ReligiousOrder")
    ReligiousCommunity = apps.get_model("org", "ReligiousCommunity")

    types = {t.code: t for t in NodeType.objects.all()}
    tree = _Tree(Node)

    def migrate(legacy_model, legacy_id, *, type_code, name, parent, code=None, **extra):
        existing = Node.objects.filter(legacy_model=legacy_model, legacy_id=legacy_id).first()
        if existing is not None:
            return existing
        return tree.add(
            parent=parent,
            type=types[type_code],
            name=name,
            code=_unique_code(Node, code or f"{type_code.upper()}-{legacy_id}"),
            legacy_model=legacy_model,
            legacy_id=legacy_id,
            **extra,
        )

    provinces = {
        p.id: migrate("org.Province", p.id, type_code="province", name=p.name, parent=None, code=p.code)
        for p in Province.objects.order_by("id")
    }
    dioceses = {
        d.id: migrate(
            "org.Diocese", d.id, type_code="diocese", name=d.name, parent=provinces[d.province_id], code=d.code
        )
        for d in Diocese.objects.order_by("id")
    }
    deaneries = {}
    for d in Deanery.objects.order_by("id"):
        deaneries[d.id] = migrate("org.Deanery", d.id, type_code="doyenne", name=d.name, parent=dioceses[d.diocese_id])
    parishes = {}
    for p in Parish.objects.order_by("id"):
        parent = deaneries.get(p.deanery_id) or dioceses[p.diocese_id]
        # Le parent a pu être rechargé ailleurs : on relit son chemin et numchild à jour.
        parent.refresh_from_db()
        parishes[p.id] = migrate(
            "org.Parish", p.id, type_code="paroisse", name=p.name, parent=parent, address=p.address, city=p.city
        )
    for c in Church.objects.order_by("id"):
        if Place.objects.filter(legacy_id=c.id).exists():
            continue
        Place.objects.create(
            node=parishes[c.parish_id],
            name=c.name,
            kind=CHURCH_KIND.get(c.church_type, "chapelle"),
            is_main=c.is_main,
            address=c.address,
            city=c.city,
            lat=c.latitude,
            lng=c.longitude,
            is_active=c.is_active,
            legacy_id=c.id,
        )
    orders = {
        o.id: migrate("org.ReligiousOrder", o.id, type_code="institut", name=f"{o.name} ({o.abbreviation})", parent=None)
        for o in ReligiousOrder.objects.order_by("id")
    }
    for c in ReligiousCommunity.objects.order_by("id"):
        parent = orders[c.order_id]
        parent.refresh_from_db()
        migrate(
            "org.ReligiousCommunity",
            c.id,
            type_code="communaute",
            name=c.name,
            parent=parent,
            located_in=dioceses[c.diocese_id],
        )


def backwards(apps, schema_editor):
    Node = apps.get_model("hierarchy", "Node")
    Place = apps.get_model("hierarchy", "PlaceOfWorship")
    Place.objects.filter(legacy_id__isnull=False).delete()
    for legacy in Node.objects.exclude(legacy_model="").order_by("depth"):
        subtree = Node.objects.filter(path__startswith=legacy.path)
        Place.objects.filter(node__in=subtree).delete()
        subtree.delete()
    # Les compteurs d'enfants des nœuds restants sont recalculés.
    for node in Node.objects.all():
        node.numchild = Node.objects.filter(path__startswith=node.path, depth=node.depth + 1).count()
        node.save(update_fields=["numchild"])


class Migration(migrations.Migration):
    dependencies = [
        ("hierarchy", "0002_seed_node_types"),
        ("org", "0003_backfill_main_church"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
