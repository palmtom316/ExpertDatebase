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


_CN_STOP_TERMS = {
    "哪些",
    "哪些规定",
    "有哪些",
    "有什么",
    "规定",
    "要求",
    "相关",
    "有关",
    "请问",
    "一下",
    "说明",
    "什么",
    "怎么",
    "如何",
    "应当",
    "应该",
    "是否",
}
_CN_STOP_CHARS = set("的了吗呢吧啊呀和及并且或与在对将把为于被就都其")


def _contains_cjk(text_value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", str(text_value or "")))


def _split_cn_run(run: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    for ch in run:
        if ch in _CN_STOP_CHARS:
            if len(buf) >= 2:
                parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    if len(buf) >= 2:
        parts.append("".join(buf))
    return parts


def _valid_cn_term(term: str) -> bool:
    t = str(term or "").strip()
    if len(t) < 2:
        return False
    if t in _CN_STOP_TERMS:
        return False
    if re.search(r"(哪些|有哪|规定|要求|什么|如何|怎么|请问)", t):
        return False
    if all(ch in _CN_STOP_CHARS for ch in t):
        return False
    return True


def _extract_cjk_terms(query_text: str, max_terms: int = 14) -> list[str]:
    q = re.sub(r"\s+", "", str(query_text or ""))
    runs = re.findall(r"[\u4e00-\u9fff]{2,36}", q)
    terms: list[str] = []
    for run in runs:
        segments = _split_cn_run(run)
        if not segments:
            segments = [run]
        for seg in segments:
            seg_len = len(seg)
            if seg_len <= 8 and _valid_cn_term(seg):
                terms.append(seg)
            for n in (2, 3):
                if seg_len < n:
                    continue
                for i in range(0, seg_len - n + 1):
                    gram = seg[i : i + n]
                    if _valid_cn_term(gram):
                        terms.append(gram)
    out: list[str] = []
    seen: set[str] = set()
    for t in terms:
        x = t.strip()
        if not x or x in seen:
            continue
        seen.add(x)
        out.append(x)
        if len(out) >= max_terms:
            break
    return out


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

    def _search_like_fallback(
        self,
        query_text: str,
        limit: int,
        selected_doc_id: str = "",
        selected_version_id: str = "",
    ) -> list[dict[str, Any]]:
        if not self._engine:
            return []
        terms = _extract_cjk_terms(query_text=query_text, max_terms=14)
        if not terms:
            return []

        normalized_query = re.sub(r"\s+", "", str(query_text or ""))
        normalized_col = "regexp_replace(COALESCE(text, ''), E'\\\\s+', '', 'g')"

        score_parts: list[str] = []
        where_parts: list[str] = []
        params: dict[str, Any] = {"limit": max(1, int(limit))}
        if selected_doc_id:
            params["doc_id"] = selected_doc_id
        if selected_version_id:
            params["version_id"] = selected_version_id
        if normalized_query and len(normalized_query) <= 40:
            params["q_phrase"] = f"%{normalized_query}%"
            score_parts.append(f"CASE WHEN {normalized_col} ILIKE :q_phrase THEN 6.0 ELSE 0 END")
            where_parts.append(f"{normalized_col} ILIKE :q_phrase")

        for idx, term in enumerate(terms):
            key = f"q_term_{idx}"
            params[key] = f"%{term}%"
            weight = 1.0 + min(len(term), 8) / 8.0
            score_parts.append(f"CASE WHEN {normalized_col} ILIKE :{key} THEN {weight:.3f} ELSE 0 END")
            where_parts.append(f"{normalized_col} ILIKE :{key}")

        if not score_parts or not where_parts:
            return []
        where_doc = "AND doc_id = :doc_id" if selected_doc_id else ""
        where_version = "AND version_id = :version_id" if selected_version_id else ""
        excerpt_limit = max(120, int(os.getenv("PG_BM25_EXCERPT_MAX_CHARS", "800")))
        score_sql = " + ".join(score_parts)
        where_sql = " OR ".join(where_parts)
        sql = text(
            f"""
            SELECT
              doc_id,
              page_no,
              LEFT(text, {excerpt_limit}) AS excerpt,
              ({score_sql}) AS score,
              COALESCE(source_path, '') AS source_path
            FROM doc_pages
            WHERE ({where_sql})
              {where_doc}
              {where_version}
            ORDER BY score DESC, page_no ASC
            LIMIT :limit
            """
        )
        try:
            with self._engine.begin() as conn:
                rows = conn.execute(sql, params).mappings().all()
        except Exception as exc:  # noqa: BLE001
            _log.warning("pg_bm25_like_fallback_failed error=%s", str(exc))
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
        selected_version_id = ""
        if isinstance(filters, dict):
            for cond in filters.get("must") or []:
                if not isinstance(cond, dict):
                    continue
                if str(cond.get("key") or "") == "doc_id":
                    selected_doc_id = str(((cond.get("match") or {}).get("value") or "")).strip()
                    continue
                if str(cond.get("key") or "") == "version_id":
                    selected_version_id = str(((cond.get("match") or {}).get("value") or "")).strip()

        where_doc = "AND doc_id = :doc_id" if selected_doc_id else ""
        where_version = "AND version_id = :version_id" if selected_version_id else ""
        excerpt_limit = max(120, int(os.getenv("PG_BM25_EXCERPT_MAX_CHARS", "800")))
        sql = text(
            f"""
            SELECT
              doc_id,
              page_no,
              LEFT(text, {excerpt_limit}) AS excerpt,
              ts_rank_cd(tsv, websearch_to_tsquery('simple', :query)) AS score,
              COALESCE(source_path, '') AS source_path
            FROM doc_pages
            WHERE tsv @@ websearch_to_tsquery('simple', :query)
              {where_doc}
              {where_version}
            ORDER BY score DESC
            LIMIT :limit
            """
        )
        params: dict[str, Any] = {"query": q, "limit": limit}
        if selected_doc_id:
            params["doc_id"] = selected_doc_id
        if selected_version_id:
            params["version_id"] = selected_version_id

        try:
            with self._engine.begin() as conn:
                rows = conn.execute(sql, params).mappings().all()
        except Exception as exc:  # noqa: BLE001
            _log.warning("pg_bm25_query_failed error=%s", str(exc))
            rows = []

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
        out = [item for item in out if item["doc_id"] and item["page_no"] > 0]
        if out:
            return out
        if _contains_cjk(q):
            return self._search_like_fallback(
                query_text=q,
                limit=limit,
                selected_doc_id=selected_doc_id,
                selected_version_id=selected_version_id,
            )
        return []
