"""Index de la file de vérification, construit sans verrouiller la table des comptes."""

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("users", "0011_person_v1")]

    operations = [
        AddIndexConcurrently(
            model_name="baseuser",
            index=models.Index(
                condition=models.Q(("etat_de_vie", "laic"), _negated=True),
                fields=["statut_verification"],
                name="users_verification_queue",
            ),
        ),
    ]
