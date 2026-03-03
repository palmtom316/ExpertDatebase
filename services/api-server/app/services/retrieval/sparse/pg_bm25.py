"""PostgreSQL tsvector sparse retrieval adapter."""

from __future__ import annotations

import os
import re
from typing import Any

from sqlalchemy import create_engine, text


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

    def search(
        self,
        query_text: str,
        top_n: int = 200,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if not self._engine:
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

        with self._engine.begin() as conn:
            rows = conn.execute(sql, params).mappings().all()

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

