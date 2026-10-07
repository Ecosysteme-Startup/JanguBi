BEGIN;

-- Extension vector : employée par les migrations initiales (colonnes d'avant ADR-018). Aucun index
-- vectoriel n'est créé : il n'y a pas de recherche vectorielle dans la plateforme (ADR-018).
DO $$
BEGIN
    EXECUTE 'CREATE EXTENSION IF NOT EXISTS vector;';
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pgvector extension could not be created : %', SQLERRM;
END$$;

-- Plein texte des versets : même configuration que la recherche (PG_TS_CONFIG = fr_unaccent,
-- créée par les migrations bible.0005 / audio.0002).
UPDATE bible_verse SET tsv = to_tsvector('fr_unaccent', text) WHERE tsv IS NULL;
CREATE INDEX IF NOT EXISTS idx_verse_tsv ON bible_verse USING gin(tsv);

COMMIT;
