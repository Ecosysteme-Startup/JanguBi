"""Versets recalculés avec la configuration sans mots vides ; colonne ``embedding`` supprimée.

``audio.0006`` filtre désormais les mots vides avant le retrait des accents dans ``fr_unaccent`` ;
les ``tsv`` des versets sont recalculés pour que l'index et les requêtes concordent. Contraction
de l'ADR-018 : ``embedding`` (vidée et retirée du modèle par ``0005``) est supprimée.
"""

from django.db import migrations


class Migration(migrations.Migration):
    # Non atomique : le DROP COLUMN valide aussitôt (verrou bref), le recalcul ne bloque pas les lectures.
    atomic = False

    dependencies = [
        ("bible", "0005_sans_embeddings_tsv_fr_unaccent"),
        ("audio", "0006_mots_vides_et_contraction"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    "ALTER TABLE bible_verse DROP COLUMN IF EXISTS embedding;",
                    reverse_sql="ALTER TABLE bible_verse ADD COLUMN IF NOT EXISTS embedding vector(768) NULL;",
                ),
            ],
        ),
        migrations.RunSQL(
            "UPDATE bible_verse SET tsv = to_tsvector('fr_unaccent', text);",
            reverse_sql="UPDATE bible_verse SET tsv = to_tsvector('fr_unaccent', text);",
        ),
    ]
