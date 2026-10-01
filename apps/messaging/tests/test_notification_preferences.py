import pytest
from rest_framework.test import APIClient

from apps.messaging.models import Notification
from apps.messaging.services_notifications import people_notify
from apps.users.tests.factories import BaseUserFactory

pytestmark = pytest.mark.django_db


def test_preferences_default_then_update():
    user = BaseUserFactory.create()
    client = APIClient()
    client.force_authenticate(user=user)

    default = client.get("/api/v1/me/notification-preferences/")
    updated = client.put(
        "/api/v1/me/notification-preferences/", {"email": False, "quiet_start": "21:00:00"}, format="json"
    )

    assert default.data["in_app"] is True and default.data["quiet_start"] == "22:00:00"
    assert updated.data["email"] is False and updated.data["quiet_start"] == "21:00:00"


def test_topic_switched_off_means_no_notification():
    wants, refuses = BaseUserFactory.create(), BaseUserFactory.create()
    client = APIClient()
    client.force_authenticate(user=refuses)
    client.put("/api/v1/me/notification-preferences/", {"topic_annonces": False}, format="json")

    count = people_notify(user_ids=[wants.pk, refuses.pk], topic="annonces", event_type="news.published", payload={})

    assert count == 1
    assert list(Notification.objects.values_list("user_id", flat=True)) == [wants.pk]
