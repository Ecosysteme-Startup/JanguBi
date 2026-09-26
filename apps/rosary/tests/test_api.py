import pytest
from rest_framework.test import APIClient

from apps.rosary.models import MysteryGroup


@pytest.fixture
def api_client():
    return APIClient()

@pytest.fixture
def setup_data():
    MysteryGroup.objects.create(name="Sorrowful", slug="sorrowful")

@pytest.mark.django_db
def test_group_list_api(api_client, setup_data):
    response = api_client.get("/api/v1/rosary/groups/")
    assert response.status_code == 200
    assert len(response.data) == 1
    assert response.data[0]["name"] == "Sorrowful"

@pytest.mark.django_db
def test_group_detail_api(api_client, setup_data):
    response = api_client.get("/api/v1/rosary/groups/sorrowful/")
    assert response.status_code == 200
    assert response.data["name"] == "Sorrowful"


@pytest.mark.django_db
def test_rosary_day_serves_fruit_and_french_labels(api_client):
    """Écart F9 : « fruit » de chaque mystère et libellés (jour, prière) en français."""
    from apps.rosary.models import Mystery, MysteryPrayer, Prayer, RosaryDay

    group = MysteryGroup.objects.create(name="Joyeux", slug="joyeux")
    mystery = Mystery.objects.create(group=group, order=1, title="L'Annonciation", fruit="L'humilité")
    prayer = Prayer.objects.create(type=Prayer.Type.HAIL_MARY, text="Je vous salue, Marie…", language="fr")
    MysteryPrayer.objects.create(mystery=mystery, prayer=prayer, order=1)
    RosaryDay.objects.create(weekday=RosaryDay.Weekday.MONDAY, group=group)

    response = api_client.get("/api/v1/rosary/day/0/")

    assert response.status_code == 200
    day = response.data["day"]
    assert day["weekday_display"] == "Lundi"
    [served] = day["group"]["mysteries"]
    assert served["fruit"] == "L'humilité"
    assert served["prayers"][0]["prayer"]["type_display"] == "Je vous salue Marie"


@pytest.mark.django_db
def test_fruits_migration_fills_only_empty_fruits():
    import importlib

    from django.apps import apps

    from apps.rosary.models import Mystery

    migration = importlib.import_module("apps.rosary.migrations.0003_mystere_fruit_libelles_fr")
    group = MysteryGroup.objects.create(name="Glorieux", slug="glorieux")
    empty = Mystery.objects.create(group=group, order=1, title="La Résurrection")
    kept = Mystery.objects.create(group=group, order=2, title="L'Ascension", fruit="Saisi à la main")

    migration.fruits_fill(apps, None)

    empty.refresh_from_db()
    kept.refresh_from_db()
    assert empty.fruit == "La foi"
    assert kept.fruit == "Saisi à la main"


@pytest.mark.django_db
def test_fruits_relecture_migration_replaces_only_old_wording():
    import importlib

    from django.apps import apps

    from apps.rosary.models import Mystery

    migration = importlib.import_module("apps.rosary.migrations.0004_mystere_fruits_relecture")
    joyeux = MysteryGroup.objects.create(name="Joyeux", slug="joyeux")
    douloureux = MysteryGroup.objects.create(name="Douloureux", slug="douloureux")
    old_joyeux = Mystery.objects.create(
        group=joyeux, order=5, title="Jésus retrouvé", fruit="La recherche de Dieu en toutes choses"
    )
    old_douloureux = Mystery.objects.create(
        group=douloureux, order=3, title="Le couronnement", fruit="Le courage face au mépris du monde"
    )
    custom = Mystery.objects.create(group=joyeux, order=4, title="La Présentation", fruit="Saisi à la main")

    migration.fruits_correct(apps, None)

    old_joyeux.refresh_from_db()
    old_douloureux.refresh_from_db()
    custom.refresh_from_db()
    assert old_joyeux.fruit == "La recherche de Dieu et la vraie sagesse"
    assert old_douloureux.fruit == "Le détachement des vanités du monde"
    assert custom.fruit == "Saisi à la main"

    migration.fruits_restore(apps, None)

    old_joyeux.refresh_from_db()
    assert old_joyeux.fruit == "La recherche de Dieu en toutes choses"


@pytest.mark.django_db
def test_fruits_relecture_migration_keeps_manual_edit():
    import importlib

    from django.apps import apps

    from apps.rosary.models import Mystery

    migration = importlib.import_module("apps.rosary.migrations.0004_mystere_fruits_relecture")
    joyeux = MysteryGroup.objects.create(name="Joyeux", slug="joyeux")
    edited = Mystery.objects.create(group=joyeux, order=5, title="Jésus retrouvé", fruit="Autre formulation")

    migration.fruits_correct(apps, None)

    edited.refresh_from_db()
    assert edited.fruit == "Autre formulation"


def test_seed_file_carries_corrected_fruits():
    import json
    from pathlib import Path

    from django.conf import settings

    path = Path(settings.BASE_DIR) / "init" / "rosary" / "format" / "json" / "rosary_french.json"
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert "en toutes choses" not in raw
    assert "mépris du monde" not in raw
    for day in data.values():
        if not isinstance(day, dict) or "group" not in day:
            continue
        fruits = {m["order"]: m.get("fruit") for m in day.get("mysteries", [])}
        if day["group"] == "Joyeux":
            assert fruits[5] == "La recherche de Dieu et la vraie sagesse"
        if day["group"] == "Douloureux":
            assert fruits[3] == "Le détachement des vanités du monde"
