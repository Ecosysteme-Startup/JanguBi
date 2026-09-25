"""Index des fenêtres d'activité, construits sans verrouiller la table des comptes."""

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("users", "0014_person_activity")]

    operations = [
        AddIndexConcurrently(
            model_name="baseuser", index=models.Index(fields=["last_seen_on"], name="users_last_seen_idx")
        ),
        AddIndexConcurrently(
            model_name="baseuser", index=models.Index(fields=["last_mfa_on"], name="users_last_mfa_idx")
        ),
    ]
