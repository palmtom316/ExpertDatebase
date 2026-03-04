"""PostgreSQL tsvector sparse retrieval adapter."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from sqlalchemy import create_engine, text

_log = logging.getLogger(__name__)


def _sanitize_query_text(query_text: str) -> str:
    """Normalize user query for websearch_to_tsquery safety and stability."""
    q = str(query_text or "").strip()
    if not q:
        return ""
    # Standard numbers often include "/" and "-" (e.g., DL/T-5222-2005).
    # Replace with spaces to avoid tsquery operator distortion.
    q = re.sub(r"[/-]+", " ", q)
    # Remove tsquery operator/control chars.
    q = re.sub(r"[&|!():*<>]", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q


class PgBM25SparseRetriever:
    """Query `doc_pages` table using PostgreSQL full-text ranking."""

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = str(database_url or os.getenv("DATABASE_URL") or "").strip()
        self._engine = create_engine(self.database_url, pool_pre_ping=True) if self.database_url else None
        self._schema_ready = False

    def _ensure_schema(self) -> None:
        if self._schema_ready or not self._engine:
            return
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS doc_pages (
                      id SERIAL PRIMARY KEY,
                      doc_id VARCHAR(64) NOT NULL,
                      version_id VARCHAR(64) NOT NULL,
                      page_no INTEGER NOT NULL,
                      text TEXT NOT NULL DEFAULT '',
                      source_path VARCHAR(512),
                      tsv tsvector,
                      created_at TIMESTAMP NOT NULL DEFAULT now(),
                      UNIQUE (doc_id, page_no)
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_doc_pages_tsv ON doc_pages USING gin(tsv)"))
            conn.execute(
                text(
                    """
                    CREATE OR REPLACE FUNCTION doc_pages_tsv_update() RETURNS trigger AS $$
                    BEGIN
                        NEW.tsv := to_tsvector('simple', COALESCE(NEW.text, ''));
                        RETURN NEW;
                    END;
                    $$ LANGUAGE plpgsql;
                    """
                )
            )
            conn.execute(text("DROP TRIGGER IF EXISTS doc_pages_tsv_trigger ON doc_pages"))
            conn.execute(
                text(
                    """
                    CREATE TRIGGER doc_pages_tsv_trigger
                    BEFORE INSERT OR UPDATE OF text
                    ON doc_pages
                    FOR EACH ROW EXECUTE FUNCTION doc_pages_tsv_update();
                    """
                )
            )
        self._schema_ready = True

    def search(
        self,
        query_text: str,
        top_n: int = 200,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if not self._engine:
            return []
        try:
            self._ensure_schema()
        except Exception as exc:  # noqa: BLE001
            _log.warning("pg_bm25_schema_init_failed error=%s", str(exc))
            return []
        q = _sanitize_query_text(query_text)
        if not q:
            return []
        limit = max(1, int(top_n))

        selected_doc_id = ""
        if isinstance(filters, dict):
            for cond in filters.get("must") or []:
                if not isinstance(cond, dict):
                    continue
                if str(cond.get("key") or "") == "doc_id":
                    selected_doc_id = str(((cond.get("match") or {}).get("value") or "")).strip()
                    break

        where_doc = "AND doc_id = :doc_id" if selected_doc_id else ""
        sql = text(
            f"""
            SELECT
              doc_id,
              page_no,
              LEFT(text, 260) AS excerpt,
              ts_rank_cd(tsv, websearch_to_tsquery('simple', :query)) AS score,
              COALESCE(source_path, '') AS source_path
            FROM doc_pages
            WHERE tsv @@ websearch_to_tsquery('simple', :query)
              {where_doc}
            ORDER BY score DESC
            LIMIT :limit
            """
        )
        params: dict[str, Any] = {"query": q, "limit": limit}
        if selected_doc_id:
            params["doc_id"] = selected_doc_id

        try:
            with self._engine.begin() as conn:
                rows = conn.execute(sql, params).mappings().all()
        except Exception as exc:  # noqa: BLE001
            _log.warning("pg_bm25_query_failed error=%s", str(exc))
            return []

        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "doc_id": str(row.get("doc_id") or "").strip(),
                    "page_no": int(row.get("page_no") or 0),
                    "excerpt": str(row.get("excerpt") or "").strip(),
                    "score": float(row.get("score") or 0.0),
                    "source": "pg_bm25",
                    "source_path": str(row.get("source_path") or "").strip(),
                }
            )
        return [item for item in out if item["doc_id"] and item["page_no"] > 0]
