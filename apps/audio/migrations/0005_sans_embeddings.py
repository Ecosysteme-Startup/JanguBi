"""Sans IA ni modèle (ADR-018) : plus de vecteurs sur les pistes.

Proximité « contenu » calculée en SQL sur les métadonnées (recommendations.py). Index HNSW supprimé ;
``embedding`` vidée et, avec ``embedding_text_hash``, retirée du MODÈLE seulement : les colonnes
restent en base le temps d'une livraison, pour que l'image précédente tourne encore en cas de retour
arrière (un retour ne dé-migre pas). ``embedding_text_hash`` reçoit un défaut en base : le nouveau
code ne l'écrit plus, et la colonne est NOT NULL. Suppression physique dans une migration de
contraction ultérieure.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("audio", "0004_signalement_source"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="track",
            name="audio_track_embedding_hnsw",
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(model_name="track", name="embedding"),
                migrations.RemoveField(model_name="track", name="embedding_text_hash"),
            ],
            database_operations=[
                migrations.RunSQL(
                    "UPDATE audio_track SET embedding = NULL WHERE embedding IS NOT NULL;",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunSQL(
                    "ALTER TABLE audio_track ALTER COLUMN embedding_text_hash SET DEFAULT '';",
                    reverse_sql="ALTER TABLE audio_track ALTER COLUMN embedding_text_hash DROP DEFAULT;",
                ),
            ],
        ),
    ]
