import logging
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.db import connection

from apps.bible.services.cleaning import CleaningService
from apps.bible.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


class SearchService:
    """Service handling lexical and hybrid search across verses."""

    def __init__(self):
        self.embedding_service = EmbeddingService()
        self.pgvector_enabled = getattr(settings, "PGVECTOR_ENABLED", False)
        self.ts_config = getattr(settings, "PG_TS_CONFIG", "french")

    def search(
        self, query: str, testament_slug: Optional[str] = None,
        book_slug: Optional[str] = None, chapter_number: Optional[int] = None,
        limit: int = 100, use_hybrid: bool = False, source_file: Optional[str] = None
    ) -> List[Dict]:
        """
        Main entrypoint for search.
        Routes to hybrid or lexical based on request and settings.
        Sorts results by book/chapter/verse in the grouped output.
        """
        clean_query = CleaningService.clean_text(query)
        if not clean_query:
            return []

        # Force lexical if pgvector is off
        if use_hybrid and self.pgvector_enabled:
            raw_results = self._hybrid_search(clean_query, testament_slug, book_slug, chapter_number, limit, source_file=source_file)
        else:
            raw_results = self._lexical_search(clean_query, testament_slug, book_slug, chapter_number, limit, source_file=source_file)

        return self._group_results_by_book(raw_results)

    def verses(self, query: str, *, limit: int, source_file: Optional[str] = None) -> List[Dict]:
        """Versets (liste à plat, par pertinence) : FTS puis repli trigramme. Recherche transverse."""
        clean_query = CleaningService.clean_text(query)
        if not clean_query:
            return []
        return self._lexical_search(clean_query, None, None, None, limit, source_file=source_file)

    def _lexical_search(
        self, query: str, testament_slug: Optional[str],
        book_slug: Optional[str], chapter_number: Optional[int], limit: int, source_file: Optional[str] = "bible_fr"
    ) -> List[Dict]:
        """Full-text TSV search blended with pg_trgm trigram similarity (no external API required)."""
        # ts_config passé en PARAMÈTRE (%s::regconfig) — plus d'interpolation
        # f-string dans le SQL.
        sql = """
            SELECT
                v.id, v.chapter_id, v.number as verse_number, v.text,
                c.number as chapter_number,
                b.id as book_id, b.name as book_name, b.slug as book_slug, b.order as book_order,
                t.slug as testament_slug,
                (0.6 * ts_rank(v.tsv, plainto_tsquery(%s::regconfig, %s))
                 + 0.4 * similarity(v.text, %s)) as score
            FROM bible_verse v
            JOIN bible_chapter c ON v.chapter_id = c.id
            JOIN bible_book b ON c.book_id = b.id
            JOIN bible_testament t ON b.testament_id = t.id
            WHERE v.tsv @@ plainto_tsquery(%s::regconfig, %s)
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
        self, query: str, testament_slug: Optional[str],
        book_slug: Optional[str], chapter_number: Optional[int], limit: int, source_file: Optional[str] = "bible_fr"
    ) -> List[Dict]:
        """Pure pg_trgm similarity search used when TSV yields no results."""
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
            WHERE similarity(v.text, %s) > 0.15
        """
        params = [query, query]

        sql, params = self._apply_filters(sql, params, testament_slug, book_slug, chapter_number, source_file)

        sql += " ORDER BY score DESC, b.order, c.number, v.number LIMIT %s"
        params.append(limit)

        return self._execute_search_query(sql, params)

    def _vector_search(
        self, query: str, testament_slug: Optional[str],
        book_slug: Optional[str], chapter_number: Optional[int], limit: int, source_file: Optional[str] = "bible_fr"
    ) -> List[Dict]:
        """Recherche sémantique pure : top-k cosine via l'index HNSW (<=>).

        `1 - (embedding <=> qv)` = similarité cosine ∈ [-1, 1]. On filtre les
        embeddings NULL (sinon score NULL + l'index ne sert pas) et on ordonne
        par distance cosine pour bénéficier de l'index ANN.

        NB perf : en présence de filtres WHERE (source_file/testament/...), le
        planner PostgreSQL peut ne pas utiliser l'index HNSW et faire un scan.
        Acceptable au volume actuel (~petit corpus) ; pour un très grand corpus,
        envisager un index partiel par source ou un post-filtrage des candidats.
        """
        query_vector = self.embedding_service.compute_query_embedding(query)
        if not query_vector:
            return []

        vector_str = "[" + ",".join(str(f) for f in query_vector) + "]"

        sql = """
            SELECT
                v.id, v.chapter_id, v.number as verse_number, v.text,
                c.number as chapter_number,
                b.id as book_id, b.name as book_name, b.slug as book_slug, b.order as book_order,
                t.slug as testament_slug,
                (1.0 - (v.embedding <=> %s::vector)) as score
            FROM bible_verse v
            JOIN bible_chapter c ON v.chapter_id = c.id
            JOIN bible_book b ON c.book_id = b.id
            JOIN bible_testament t ON b.testament_id = t.id
            WHERE v.embedding IS NOT NULL
        """
        params = [vector_str]
        sql, params = self._apply_filters(sql, params, testament_slug, book_slug, chapter_number, source_file)
        sql += " ORDER BY v.embedding <=> %s::vector LIMIT %s"
        params.extend([vector_str, limit])

        return self._execute_search_query(sql, params)

    def _hybrid_search(
        self, query: str, testament_slug: Optional[str],
        book_slug: Optional[str], chapter_number: Optional[int], limit: int, alpha: float = 0.6, source_file: Optional[str] = "bible_fr"
    ) -> List[Dict]:
        """Fusionne la recherche vectorielle (cosine/HNSW) et le lexical (TSV+trgm).

        Score combiné = alpha * cosine + (1-alpha) * score_lexical. Robuste : si
        l'embedding de requête échoue (modèle indispo, etc.), on retombe sur le
        lexical seul (pas de 500).
        """
        candidate_k = limit * 3  # sur-échantillonnage avant fusion/rang final
        try:
            vector_rows = self._vector_search(
                query, testament_slug, book_slug, chapter_number, candidate_k, source_file=source_file
            )
        except Exception as e:  # provider/DB vectoriel KO -> dégradation gracieuse
            logger.warning("Vector search failed, falling back to lexical only: %s", e)
            vector_rows = []

        lexical_rows = self._lexical_search(
            query, testament_slug, book_slug, chapter_number, candidate_k, source_file=source_file
        )

        if not vector_rows:
            return lexical_rows[:limit]

        merged: Dict[int, Dict] = {}
        for row in lexical_rows:
            merged[row["id"]] = {**row, "_lex": row["score"], "_vec": 0.0}
        for row in vector_rows:
            if row["id"] in merged:
                merged[row["id"]]["_vec"] = row["score"]
            else:
                merged[row["id"]] = {**row, "_lex": 0.0, "_vec": row["score"]}

        rows = list(merged.values())
        for row in rows:
            row["score"] = alpha * row["_vec"] + (1.0 - alpha) * row["_lex"]
            row["no_internal_source"] = row["score"] < 0.15
            row.pop("_lex", None)
            row.pop("_vec", None)

        rows.sort(key=lambda r: (-r["score"], r["book_order"], r["chapter_number"], r["verse_number"]))
        return rows[:limit]

    def _apply_filters(self, sql: str, params: list, testament_slug: Optional[str], book_slug: Optional[str], chapter_number: Optional[int], source_file: Optional[str] = "bible_fr"):
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
                
                # Handle NULL scores caused by uncomputed embeddings
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
                        "verse_count": 0, # not needed in search output, usually omitted
                    },
                    "matches": []
                }

            grouped[book_id]["matches"].append({
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
                "verse_number": row["verse_number"]
            })

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
