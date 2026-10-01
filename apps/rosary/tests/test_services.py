import pytest

from apps.rosary.models import Mystery, MysteryGroup, Prayer, RosaryDay
from apps.rosary.services import RosaryService


@pytest.fixture
def rosary_data():
    group = MysteryGroup.objects.create(name="Joyful Mysteries", slug="joyful")
    mystery = Mystery.objects.create(group=group, order=1, title="The Annunciation")
    prayer = Prayer.objects.create(type=Prayer.Type.OUR_FATHER, text="Our Father...", language="en")
    day = RosaryDay.objects.create(weekday=0, group=group)  # Monday
    return group, mystery, prayer, day


@pytest.mark.django_db
def test_get_groups(rosary_data):
    groups = RosaryService.get_groups()
    assert groups.count() == 1
    assert groups.first().name == "Joyful Mysteries"


@pytest.mark.django_db
def test_get_daily_rosary(rosary_data):
    # Testing index 0 (Monday)
    daily = RosaryService.get_daily_rosary(0)
    assert daily.group.name == "Joyful Mysteries"
    assert daily.weekday == 0
    assert daily.group.mysteries.count() == 1


@pytest.mark.django_db
def test_search_text(rosary_data):
    group, mystery, prayer, day = rosary_data
    # FTS calculée à la volée : doit RÉELLEMENT trouver "Our Father..." sur "Father"
    # (avant : tsv jamais peuplé => toujours vide).
    results = RosaryService.search_text("Father")
    assert prayer in list(results)


@pytest.mark.django_db
def test_search_text_empty_query_returns_none(rosary_data):
    assert RosaryService.search_text("   ").count() == 0


@pytest.mark.django_db
def test_search_text_no_match_returns_empty(rosary_data):
    assert list(RosaryService.search_text("zzzinexistant")) == []
