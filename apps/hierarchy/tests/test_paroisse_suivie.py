import pytest
from rest_framework.test import APIClient

from apps.hierarchy.tests.factories import person

pytestmark = pytest.mark.django_db


def test_follow_a_parish_freely_and_stop(tree):
    fidele = person()
    client = APIClient()
    client.force_authenticate(user=fidele)

    followed = client.put("/api/v1/me/paroisse-suivie/", {"node_id": str(tree.saint_dominique.pk)}, format="json")
    changed = client.put("/api/v1/me/paroisse-suivie/", {"node_id": str(tree.thies_parish.pk)}, format="json")
    stopped = client.put("/api/v1/me/paroisse-suivie/", {"node_id": None}, format="json")

    assert followed.data["node"]["code"] == "T-SD"
    assert changed.data["node"]["code"] == "T-THI-CATH"
    assert stopped.data["node"] is None


def test_only_a_parish_can_be_followed(tree):
    client = APIClient()
    client.force_authenticate(user=person())
    response = client.put("/api/v1/me/paroisse-suivie/", {"node_id": str(tree.dakar.pk)}, format="json")
    assert response.status_code == 400 and response.data["error"]["code"] == "not_a_parish"
