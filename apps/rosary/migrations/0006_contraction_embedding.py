"""Contraction de l'ADR-018 : ``Prayer.embedding`` (jamais rempli, retiré du modèle par ``0005``) supprimée."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("rosary", "0005_sans_embeddings"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    "ALTER TABLE rosary_prayer DROP COLUMN IF EXISTS embedding;",
                    reverse_sql="ALTER TABLE rosary_prayer ADD COLUMN IF NOT EXISTS embedding jsonb NULL;",
                ),
            ],
        ),
    ]
