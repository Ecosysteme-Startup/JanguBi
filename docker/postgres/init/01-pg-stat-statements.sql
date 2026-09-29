-- Exécuté une seule fois, à la création du volume Postgres (docker-entrypoint-initdb.d).
-- Base existante : lancer cette commande à la main (docs/SCALING.md, « pg_stat_statements »).
-- Le module doit aussi être chargé au démarrage : shared_preload_libraries=pg_stat_statements
-- (docker-compose.yml, service db).
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
