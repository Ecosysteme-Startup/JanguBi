from datetime import time

import pytest
from django.core.management import call_command

from apps.core.exceptions import ApplicationError
from apps.hierarchy.imports import nodes_import_csv, places_import_csv
from apps.hierarchy.models import MassSchedule, Node, PlaceOfWorship
from apps.hierarchy.profiles import PILOT_PARISH_CODE
from apps.hierarchy.seeding import hierarchy_profile_load
from apps.hierarchy.tests.factories import make_node

pytestmark = pytest.mark.django_db

NODES_CSV = """code,type,name,parent_code,city
T-DIO,diocese,Diocèse test,T-DAKP,Ville
T-PAR,paroisse,Paroisse test,T-DIO,Ville
"""


# --- Import CSV (EF-HIE-06) -----------------------------------------------------


def test_dry_run_reports_every_line_and_writes_nothing(tree):
    report = nodes_import_csv(content=NODES_CSV, dry_run=True)

    assert report.as_dict()["valid"] == 2
    assert report.errors == 0
    assert not report.applied
    assert not Node.objects.filter(code__in=["T-DIO", "T-PAR"]).exists()


def test_parent_created_earlier_in_the_file_is_seen_by_the_simulation(tree):
    report = nodes_import_csv(content=NODES_CSV, dry_run=True)
    assert [line.status for line in report.lines] == ["ok", "ok"]


def test_apply_writes_everything(tree):
    report = nodes_import_csv(content=NODES_CSV, dry_run=False)

    assert report.applied
    parish = Node.objects.get(code="T-PAR")
    assert parish.city == "Ville"
    assert Node.objects.get(code="T-DIO").numchild == 1


def test_one_bad_line_rolls_back_the_whole_file(tree):
    content = NODES_CSV + "T-BAD,paroisse,Paroisse mal placée,T-PAR,\nT-X,inconnu,Type inconnu,T-DIO,\n,ceb,,T-PAR,\n"

    report = nodes_import_csv(content=content, dry_run=False)

    assert not report.applied
    assert [(line.line, line.status) for line in report.lines] == [
        (2, "ok"),
        (3, "ok"),
        (4, "error"),
        (5, "error"),
        (6, "error"),
    ]
    assert "ne peut pas être rattaché" in report.lines[2].message
    assert "Type de nœud inconnu" in report.lines[3].message
    assert "nom est obligatoire" in report.lines[4].message
    assert not Node.objects.filter(code__in=["T-DIO", "T-PAR"]).exists()


def test_missing_columns_are_reported(db):
    with pytest.raises(ApplicationError) as exc:
        nodes_import_csv(content="code,name\nX,Y\n")
    assert exc.value.extra["missing"] == ["type", "parent_code"]


def test_places_import(tree):
    content = (
        "node_code,name,kind,is_main\n"
        "T-SD,Église Saint-Dominique,eglise_paroissiale,oui\n"
        "T-SD,Chapelle,chapelle,\n"
        "T-SD,Seconde principale,chapelle,oui\n"
    )

    dry = places_import_csv(content=content, dry_run=True)
    assert [line.status for line in dry.lines] == ["ok", "ok", "error"]

    ok = places_import_csv(content=content.rsplit("\n", 2)[0] + "\n", dry_run=False)
    assert ok.applied
    assert PlaceOfWorship.objects.filter(node=tree.saint_dominique).count() == 2


def test_import_command(tree, tmp_path):
    path = tmp_path / "nodes.csv"
    path.write_text(NODES_CSV, encoding="utf-8")

    call_command("import_hierarchy_csv", "nodes", str(path))
    assert not Node.objects.filter(code="T-DIO").exists()

    call_command("import_hierarchy_csv", "nodes", str(path), "--apply")
    assert Node.objects.filter(code="T-DIO").exists()


# --- Profil « Sénégal » (EF-HIE-07) ----------------------------------------------


def test_senegal_profile_loads_the_expected_tree(db):
    report = hierarchy_profile_load(profile="senegal")

    assert report.created["nodes"] == 14
    province = Node.objects.get(code="DAKP")
    assert Node.objects.filter(type__code="diocese", path__startswith=province.path).count() == 7
    dakar = Node.objects.get(code="DAK")
    assert Node.objects.filter(type__code="doyenne", path__startswith=dakar.path).count() == 5

    pilot = Node.objects.get(code=PILOT_PARISH_CODE)
    assert pilot.is_active_on_platform
    places = PlaceOfWorship.objects.filter(node=pilot)
    assert set(places.values_list("name", "is_main")) == {
        ("Église Saint-Dominique", True),
        ("Chapelle de la Cité universitaire", False),
    }
    church = places.get(is_main=True)
    sunday = MassSchedule.objects.filter(place=church, weekday=6, kind="messe")
    assert list(sunday.values_list("start_time", flat=True)) == [time(7, 30), time(9, 30), time(11, 30), time(18, 30)]
    assert MassSchedule.objects.filter(place=church, weekday__lte=4, kind="messe").count() == 10
    confession = MassSchedule.objects.get(place=church, kind="confession")
    assert (confession.weekday, confession.start_time, confession.end_time) == (5, time(16), time(18))


def test_senegal_profile_is_idempotent(db):
    hierarchy_profile_load(profile="senegal")
    counts = (Node.objects.count(), PlaceOfWorship.objects.count(), MassSchedule.objects.count())

    report = hierarchy_profile_load(profile="senegal")

    assert report.created == {"node_types": 0, "nodes": 0, "places": 0, "schedules": 0}
    assert (Node.objects.count(), PlaceOfWorship.objects.count(), MassSchedule.objects.count()) == counts


def test_senegal_profile_reuses_nodes_found_by_name(db):
    """Un nœud migré depuis org (même nom, autre code) n'est pas dupliqué."""
    province = make_node("province", "Province ecclésiastique de Dakar", code="LEGACY-P")
    make_node("diocese", "Archidiocèse de Dakar", province, code="LEGACY-D")

    hierarchy_profile_load(profile="senegal")

    assert Node.objects.filter(type__code="province").count() == 1
    assert Node.objects.filter(name="Archidiocèse de Dakar").count() == 1
    assert Node.objects.get(code="LEGACY-D").numchild == 6  # 5 doyennés + Saint-Dominique


def test_unknown_profile(db):
    with pytest.raises(ApplicationError):
        hierarchy_profile_load(profile="atlantide")


def test_seed_command(db):
    call_command("seed_hierarchy_profile", "senegal")
    assert Node.objects.filter(code=PILOT_PARISH_CODE).exists()
