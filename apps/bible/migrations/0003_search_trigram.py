"""Recherche approchée sur le texte des versets (pg_trgm)."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("bible", "0002_initial")]

    operations = [
        migrations.RunSQL(
            sql=[
                "CREATE EXTENSION IF NOT EXISTS pg_trgm;",
                "CREATE INDEX IF NOT EXISTS idx_verse_trgm ON bible_verse USING gin(text gin_trgm_ops);",
            ],
            reverse_sql=["DROP INDEX IF EXISTS idx_verse_trgm;"],
        ),
    ]
