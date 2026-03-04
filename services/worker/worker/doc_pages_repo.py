"""Worker-side doc_pages upsert for sparse retrieval."""

from __future__ import annotations

import os
from typing import Any, Protocol

from sqlalchemy import create_engine, text


def _sanitize_text(value: Any) -> str:
    s = str(value or "")
    return "".join(ch for ch in s if ch in ("\n", "\t") or ord(ch) >= 32).strip()


class DocPagesRepo(Protocol):
    def upsert_pages(self, doc_id: str, version_id: str, pages: list[dict[str, Any]]) -> int:
        raise NotImplementedError


class NoopDocPagesRepo:
    def upsert_pages(self, doc_id: str, version_id: str, pages: list[dict[str, Any]]) -> int:  # noqa: ARG002
        return 0


class SQLDocPagesRepo:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self._schema_ready = False

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self.engine.begin() as conn:
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

    def upsert_pages(self, doc_id: str, version_id: str, pages: list[dict[str, Any]]) -> int:
        self._ensure_schema()
        rows: list[dict[str, Any]] = []
        for page in pages:
            page_no = int(page.get("page_no") or 0)
            text_value = _sanitize_text(page.get("text") or "")
            if page_no <= 0 or not text_value:
                continue
            rows.append(
                {
                    "doc_id": doc_id,
                    "version_id": version_id,
                    "page_no": page_no,
                    "text": text_value,
                    "source_path": _sanitize_text(page.get("source_path") or "") or None,
                }
            )
        if not rows:
            return 0

        upsert_sql = text(
            """
            INSERT INTO doc_pages (doc_id, version_id, page_no, text, source_path)
            VALUES (:doc_id, :version_id, :page_no, :text, :source_path)
            ON CONFLICT (doc_id, page_no)
            DO UPDATE
            SET version_id = EXCLUDED.version_id,
                text = EXCLUDED.text,
                source_path = EXCLUDED.source_path
            """
        )
        with self.engine.begin() as conn:
            conn.execute(upsert_sql, rows)
        return len(rows)


def build_doc_pages_repo_from_env() -> DocPagesRepo:
    if str(os.getenv("ENABLE_PG_BM25", "1")).strip().lower() in {"0", "false", "no", "off"}:
        return NoopDocPagesRepo()
    database_url = str(os.getenv("DATABASE_URL") or "").strip()
    if not database_url:
        return NoopDocPagesRepo()
    return SQLDocPagesRepo(database_url=database_url)
