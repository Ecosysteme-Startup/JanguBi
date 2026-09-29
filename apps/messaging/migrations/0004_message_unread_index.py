# Lot B2 : index partiel des messages non lus (docs/SCALING.md, « Index »).
# Créé sans verrouiller les écritures (CONCURRENTLY), donc hors transaction.

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("messaging", "0003_push_preference_device_disabled"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="message",
            index=models.Index(
                condition=models.Q(("deleted_at__isnull", True), ("read_at__isnull", True)),
                fields=["conversation", "sender"],
                name="msg_conv_unread_idx",
            ),
        ),
    ]
