"""Recherche dans les versets, sans IA ni modèle (ADR-018) : plein texte PostgreSQL et pg_trgm.

1. Plein texte : ``tsv`` (configuration ``fr_unaccent`` : français, sans accents, racinisé) et
   ``websearch_to_tsquery`` (« expression entre guillemets », ``-mot`` pour exclure, ``or``).
   Score = 0,6 × ``ts_rank`` + 0,4 × similarité trigramme du texte.
2. Repli trigramme quand le plein texte ne trouve rien (faute de frappe, mot tronqué) :
   opérateur ``%`` sur l'index GIN ``idx_verse_trgm``, seuil ``TRIGRAM_THRESHOLD``.
"""

import logging
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.db import connection, transaction

from apps.bible.services.cleaning import CleaningService

logger = logging.getLogger(__name__)

# Seuil de similarité trigramme du repli (0 à 1) : fixé pour la transaction (SET LOCAL), l'opérateur
# « % » peut alors utiliser l'index GIN, là où « similarity() > seuil » parcourt toute la table.
TRIGRAM_THRESHOLD = 0.15


class SearchService:
    """Recherche plein texte + trigrammes dans les versets."""

    def __init__(self):
        self.ts_config = getattr(settings, "PG_TS_CONFIG", "fr_unaccent")

    def search(
        self,
        query: str,
        testament_slug: Optional[str] = None,
        book_slug: Optional[str] = None,
        chapter_number: Optional[int] = None,
        limit: int = 100,
        use_hybrid: bool = False,
        source_file: Optional[str] = None,
    ) -> List[Dict]:
        """Point d'entrée : résultats groupés par livre.

        ``use_hybrid`` est accepté pour compatibilité (anciens clients) et ignoré : il n'y a plus de
        recherche vectorielle (ADR-018).
        """
        clean_query = CleaningService.clean_text(query)
        if not clean_query:
            return []
        raw_results = self._lexical_search(
            clean_query, testament_slug, book_slug, chapter_number, limit, source_file=source_file
        )
        return self._group_results_by_book(raw_results)

    def verses(self, query: str, *, limit: int, source_file: Optional[str] = None) -> List[Dict]:
        """Versets (liste à plat, par pertinence) : FTS puis repli trigramme. Recherche transverse."""
        clean_query = CleaningService.clean_text(query)
        if not clean_query:
            return []
        return self._lexical_search(clean_query, None, None, None, limit, source_file=source_file)

    def _lexical_search(
        self,
        query: str,
        testament_slug: Optional[str],
        book_slug: Optional[str],
        chapter_number: Optional[int],
        limit: int,
        source_file: Optional[str] = "bible_fr",
    ) -> List[Dict]:
        """Plein texte (``tsv``) mêlé à la similarité trigramme du texte."""
        # ts_config passé en PARAMÈTRE (%s::regconfig) — plus d'interpolation
        # f-string dans le SQL.
        sql = """
            SELECT
                v.id, v.chapter_id, v.number as verse_number, v.text,
                c.number as chapter_number,
                b.id as book_id, b.name as book_name, b.slug as book_slug, b.order as book_order,
                t.slug as testament_slug,
                (0.6 * ts_rank(v.tsv, websearch_to_tsquery(%s::regconfig, %s))
                 + 0.4 * similarity(v.text, %s)) as score
            FROM bible_verse v
            JOIN bible_chapter c ON v.chapter_id = c.id
            JOIN bible_book b ON c.book_id = b.id
            JOIN bible_testament t ON b.testament_id = t.id
            WHERE v.tsv @@ websearch_to_tsquery(%s::regconfig, %s)
        """
        params = [self.ts_config, query, query, self.ts_config, query]

        sql, params = self._apply_filters(sql, params, testament_slug, book_slug, chapter_number, source_file)

        sql += " ORDER BY score DESC, b.order, c.number, v.number LIMIT %s"
        params.append(limit)

        results = self._execute_search_query(sql, params)

        # Fallback to pure trigram when TSV finds nothing (short query, typo, accent mismatch)
        if not results:
            return self._trigram_fallback(query, testament_slug, book_slug, chapter_number, limit, source_file)

        return results

    def _trigram_fallback(
        self,
        query: str,
        testament_slug: Optional[str],
        book_slug: Optional[str],
        chapter_number: Optional[int],
        limit: int,
        source_file: Optional[str] = "bible_fr",
    ) -> List[Dict]:
        """Repli trigramme (fautes de frappe) quand le plein texte ne trouve rien, sur l'index GIN."""
        sql = """
            SELECT
                v.id, v.chapter_id, v.number as verse_number, v.text,
                c.number as chapter_number,
                b.id as book_id, b.name as book_name, b.slug as book_slug, b.order as book_order,
                t.slug as testament_slug,
                similarity(v.text, %s) as score
            FROM bible_verse v
            JOIN bible_chapter c ON v.chapter_id = c.id
            JOIN bible_book b ON c.book_id = b.id
            JOIN bible_testament t ON b.testament_id = t.id
            WHERE v.text %% %s
        """
        params = [query, query]

        sql, params = self._apply_filters(sql, params, testament_slug, book_slug, chapter_number, source_file)

        sql += " ORDER BY score DESC, b.order, c.number, v.number LIMIT %s"
        params.append(limit)

        # Seuil local à la transaction... mais sous ATOMIC_REQUESTS, atomic() n'ouvre qu'un savepoint et
        # un SET LOCAL survit à son RELEASE : on remet donc l'ancienne valeur, sinon les recherches
        # trigrammes suivantes de la même requête HTTP (audio, recherche globale) hériteraient de 0,15.
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT current_setting('pg_trgm.similarity_threshold'), "
                    "set_config('pg_trgm.similarity_threshold', %s, true)",
                    [str(TRIGRAM_THRESHOLD)],
                )
                previous = cursor.fetchone()[0]
            try:
                return self._execute_search_query(sql, params)
            finally:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT set_config('pg_trgm.similarity_threshold', %s, true)", [previous])

    def _apply_filters(
        self,
        sql: str,
        params: list,
        testament_slug: Optional[str],
        book_slug: Optional[str],
        chapter_number: Optional[int],
        source_file: Optional[str] = "bible_fr",
    ):
        """Évite d'écrire la même logique d'ajout de paramètres WHERE pour chaque méthode de recherche."""
        if source_file:
            sql += " AND v.source_file = %s"
            params.append(source_file)
        if testament_slug:
            sql += " AND t.slug = %s"
            params.append(testament_slug)
        if book_slug:
            sql += " AND b.slug = %s"
            params.append(book_slug)
        if chapter_number:
            sql += " AND c.number = %s"
            params.append(chapter_number)
        return sql, params

    def _execute_search_query(self, sql: str, params: list) -> List[Dict]:
        """Fusionne l'exécution du curseur de DB en un seul endroit propre."""
        results = []
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            columns = [col[0] for col in cursor.description]
            for row in cursor.fetchall():
                row_dict = dict(zip(columns, row))

                score = row_dict.get("score")
                if score is None:
                    score = 0.0
                    row_dict["score"] = score

                row_dict["no_internal_source"] = score < 0.15
                results.append(row_dict)
        return results

    def _group_results_by_book(self, raw_results: List[Dict]) -> List[Dict]:
        """Groups flat SQL results into the nested structure expected by the API."""
        grouped: Dict[int, Dict[str, Any]] = {}
        for row in raw_results:
            book_id = row["book_id"]
            if book_id not in grouped:
                grouped[book_id] = {
                    "book": {
                        "id": book_id,
                        "name": row["book_name"],
                        "slug": row["book_slug"],
                        "order": row["book_order"],
                        "testament": row["testament_slug"],
                        "verse_count": 0,  # not needed in search output, usually omitted
                    },
                    "matches": [],
                }

            grouped[book_id]["matches"].append(
                {
                    "verse": {
                        "id": row["id"],
                        "number": row["verse_number"],
                        "chapter": {"number": row["chapter_number"]},
                        "text": row["text"],
                    },
                    "score": round(row["score"], 4),
                    "no_internal_source": row["no_internal_source"],
                    "book_order": row["book_order"],
                    "chapter_number": row["chapter_number"],
                    "verse_number": row["verse_number"],
                }
            )

        # Convert to list and sort by book order
        result_list = list(grouped.values())
        result_list.sort(key=lambda x: x["book"]["order"])

        # Sort verses within each book
        for group in result_list:
            group["matches"].sort(key=lambda x: (x["chapter_number"], x["verse_number"]))
            # Clean up sort keys
            for m in group["matches"]:
                m.pop("book_order")
                m.pop("chapter_number")
                m.pop("verse_number")

        return result_list
