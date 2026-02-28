"""Document registry adapters with JSON and SQL backends."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import create_engine, text


class DocRegistry(Protocol):
    def add_document(self, doc: dict[str, Any], version: dict[str, Any]) -> None:
        raise NotImplementedError


class JSONDocRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text('{"documents": [], "versions": []}', encoding="utf-8")

    def _read(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def add_document(self, doc: dict[str, Any], version: dict[str, Any]) -> None:
        payload = self._read()
        payload["documents"].append(doc)
        payload["versions"].append(version)
        self._write(payload)


class SQLDocRegistry:
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
                    CREATE TABLE IF NOT EXISTS documents (
                        id VARCHAR(64) PRIMARY KEY,
                        name VARCHAR(512) NOT NULL,
                        doc_type VARCHAR(64),
                        created_at TIMESTAMP NOT NULL DEFAULT now()
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS document_versions (
                        id VARCHAR(64) PRIMARY KEY,
                        doc_id VARCHAR(64) NOT NULL REFERENCES documents(id),
                        version_no INTEGER NOT NULL,
                        storage_key VARCHAR(1024) NOT NULL,
                        status VARCHAR(64) NOT NULL,
                        mineru_json_key VARCHAR(1024),
                        mineru_md_key VARCHAR(1024),
                        notes TEXT,
                        created_at TIMESTAMP NOT NULL DEFAULT now()
                    )
                    """
                )
            )
        self._schema_ready = True

    def add_document(self, doc: dict[str, Any], version: dict[str, Any]) -> None:
        self._ensure_schema()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO documents (id, name, doc_type, created_at)
                    VALUES (:id, :name, :doc_type, now())
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "id": doc["id"],
                    "name": doc.get("name", "unknown"),
                    "doc_type": doc.get("doc_type"),
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO document_versions (id, doc_id, version_no, storage_key, status, created_at)
                    VALUES (:id, :doc_id, :version_no, :storage_key, :status, now())
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "id": version["id"],
                    "doc_id": version["doc_id"],
                    "version_no": int(version.get("version_no", 1)),
                    "storage_key": version["storage_key"],
                    "status": version.get("status", "uploaded"),
                },
            )


def build_doc_registry_from_env() -> DocRegistry:
    backend = os.getenv("DOC_REGISTRY_BACKEND", "auto").lower()
    if backend == "json":
        return JSONDocRegistry(Path(os.getenv("DOC_REGISTRY_PATH", ".runtime/registry.json")))

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return SQLDocRegistry(database_url)

    return JSONDocRegistry(Path(os.getenv("DOC_REGISTRY_PATH", ".runtime/registry.json")))
