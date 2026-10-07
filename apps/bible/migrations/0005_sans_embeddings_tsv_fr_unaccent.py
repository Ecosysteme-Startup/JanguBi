"""Sans IA ni modèle (ADR-018) : plus de vecteurs sur les versets, plein texte sans accents.

1. Recherche vectorielle abandonnée (le modèle d'embeddings demandait 3 à 6 Go de mémoire pour un
   usage que le plein texte couvre) : index HNSW supprimé (sans bloquer les lectures), colonne ``embedding`` vidée et retirée
   du MODÈLE seulement. Elle reste en base le temps d'une livraison, pour que l'image précédente
   (qui la lit) tourne encore en cas de retour arrière — un retour ne dé-migre pas. Suppression
   physique dans une migration de contraction ultérieure.
2. ``tsv`` recalculé avec ``fr_unaccent`` (français, sans accents, racinisé), la configuration que
   la recherche emploie désormais : « eglise » trouve « Église ». La configuration est créée ici si
   elle n'existe pas encore (même définition que ``audio.0002``, idempotente), pour ne pas dépendre
   de l'ordre des applications.

Retour arrière sans dé-migrer : l'image précédente tourne, mais interroge en ``french`` un ``tsv`` en
``fr_unaccent`` ; les mots accentués passent alors par le repli trigramme (recherche dégradée, pas cassée).

L'extension ``vector`` reste installée : les migrations initiales l'emploient.
"""

from django.db import migrations

FR_UNACCENT = """
CREATE EXTENSION IF NOT EXISTS unaccent;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'fr_unaccent') THEN
        CREATE TEXT SEARCH CONFIGURATION fr_unaccent (COPY = french);
        ALTER TEXT SEARCH CONFIGURATION fr_unaccent
            ALTER MAPPING FOR hword, hword_part, word WITH unaccent, french_stem;
    END IF;
END
$$;
"""


class Migration(migrations.Migration):
    # Non atomique : chaque étape valide aussitôt. Un DROP INDEX dans la transaction garderait un verrou
    # ACCESS EXCLUSIVE sur bible_verse pendant les deux UPDATE (plusieurs secondes) et bloquerait toute
    # lecture de verset de l'image en service. Chaque étape est rejouable si la migration s'interrompt.
    atomic = False

    dependencies = [
        ("bible", "0004_reco_pour_vous"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.RemoveIndex(model_name="verse", name="idx_verse_embedding_hnsw")],
            database_operations=[
                migrations.RunSQL(
                    "DROP INDEX CONCURRENTLY IF EXISTS idx_verse_embedding_hnsw;",
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.RemoveField(model_name="verse", name="embedding")],
            database_operations=[
                migrations.RunSQL(
                    "UPDATE bible_verse SET embedding = NULL WHERE embedding IS NOT NULL;",
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
        migrations.RunSQL(FR_UNACCENT, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(
            "UPDATE bible_verse SET tsv = to_tsvector('fr_unaccent', text);",
            reverse_sql="UPDATE bible_verse SET tsv = to_tsvector('french', text);",
        ),
    ]
