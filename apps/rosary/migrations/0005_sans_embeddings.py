"""Sans IA ni modèle (ADR-018) : champ ``embedding`` des prières (jamais rempli) retiré du MODÈLE.

La colonne (nullable) reste en base le temps d'une livraison, pour que l'image précédente tourne
encore en cas de retour arrière ; suppression physique dans une migration de contraction ultérieure.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("rosary", "0004_mystere_fruits_relecture"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.RemoveField(model_name="prayer", name="embedding")],
        ),
    ]
