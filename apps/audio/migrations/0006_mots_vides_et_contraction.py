"""Plein texte : mots vides filtrés avant le retrait des accents ; colonnes de vecteurs supprimées.

1. ``fr_unaccent`` ôtait les accents AVANT le filtre des mots vides de ``french_stem`` : « était »,
   « été », « à » devenaient « etait », « ete », « a » et restaient indexés. Un dictionnaire
   ``fr_mots_vides`` (liste ``french`` de PostgreSQL, ``ACCEPT = false``) les écarte désormais en
   premier ; les autres mots passent à ``unaccent`` puis ``french_stem``. Les vecteurs des pistes sont
   recalculés (même requête que ``services.track_search_index``, figée ici). ``bible.0006`` recalcule
   les versets.
2. Contraction de l'ADR-018 : ``embedding`` et ``embedding_text_hash`` (vidées et retirées du modèle
   par ``0005``) sont supprimées. L'image précédente (sans IA) ne les lit plus.
"""

from django.db import migrations

MOTS_VIDES = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_ts_dict WHERE dictname = 'fr_mots_vides') THEN
        CREATE TEXT SEARCH DICTIONARY fr_mots_vides (TEMPLATE = simple, STOPWORDS = french, ACCEPT = false);
    END IF;
END
$$;
ALTER TEXT SEARCH CONFIGURATION fr_unaccent
    ALTER MAPPING FOR hword, hword_part, word WITH fr_mots_vides, unaccent, french_stem;
"""

MOTS_VIDES_INVERSE = """
ALTER TEXT SEARCH CONFIGURATION fr_unaccent
    ALTER MAPPING FOR hword, hword_part, word WITH unaccent, french_stem;
"""

RECALCUL_PISTES = """
UPDATE audio_track t SET search_vector =
    setweight(to_tsvector('fr_unaccent', coalesce(t.title, '')), 'A')
    || setweight(to_tsvector('fr_unaccent',
        coalesce((SELECT s.name FROM audio_audiosource s WHERE s.id = t.source_id), '') || ' ' ||
        coalesce((SELECT a.title FROM audio_album a WHERE a.id = t.album_id), '') || ' ' ||
        array_to_string(t.performers, ' ') || ' ' || t.composer), 'B')
    || setweight(to_tsvector('fr_unaccent',
        array_to_string(t.tags, ' ') || ' ' || t.liturgical_season || ' ' || t.description), 'C');
"""


class Migration(migrations.Migration):
    # Non atomique : chaque étape valide aussitôt (verrou bref à la suppression des colonnes).
    atomic = False

    dependencies = [
        ("audio", "0005_sans_embeddings"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    "ALTER TABLE audio_track DROP COLUMN IF EXISTS embedding, DROP COLUMN IF EXISTS embedding_text_hash;",
                    # Retour : colonnes recréées telles que 0005 les laisse (0005 se défait ensuite).
                    reverse_sql=(
                        "ALTER TABLE audio_track ADD COLUMN IF NOT EXISTS embedding vector(768) NULL, "
                        "ADD COLUMN IF NOT EXISTS embedding_text_hash varchar(64) NOT NULL DEFAULT '';"
                    ),
                ),
            ],
        ),
        migrations.RunSQL(MOTS_VIDES, reverse_sql=MOTS_VIDES_INVERSE),
        migrations.RunSQL(RECALCUL_PISTES, reverse_sql=RECALCUL_PISTES),
    ]
