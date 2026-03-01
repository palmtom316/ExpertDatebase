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

    def list_versions(
        self,
        statuses: list[str] | None = None,
        limit: int | None = None,
        doc_type: str | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    def update_version_status(self, version_id: str, status: str, notes: dict[str, Any] | None = None) -> None:
        raise NotImplementedError

    def delete_version(self, version_id: str) -> dict[str, Any] | None:
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

    def list_versions(
        self,
        statuses: list[str] | None = None,
        limit: int | None = None,
        doc_type: str | None = None,
    ) -> list[dict[str, Any]]:
        payload = self._read()
        items = payload.get("versions", [])
        doc_map = {
            str(d.get("id")): str(d.get("doc_type") or "")
            for d in payload.get("documents", [])
            if isinstance(d, dict) and d.get("id")
        }
        if statuses:
            allowed = set(statuses)
            items = [v for v in items if v.get("status") in allowed]
        if doc_type:
            normalized = str(doc_type).strip()
            items = [v for v in items if str(doc_map.get(str(v.get("doc_id") or ""), "")).strip() == normalized]
        if limit is not None:
            items = items[:limit]
        normalized_items: list[dict[str, Any]] = []
        for item in items:
            row = dict(item)
            row["doc_type"] = doc_map.get(str(item.get("doc_id") or ""), "")
            normalized_items.append(row)
        return normalized_items

    def update_version_status(self, version_id: str, status: str, notes: dict[str, Any] | None = None) -> None:
        payload = self._read()
        for version in payload.get("versions", []):
            if version.get("id") == version_id:
                version["status"] = status
                if notes is not None:
                    version["notes"] = notes
                break
        self._write(payload)

    def delete_version(self, version_id: str) -> dict[str, Any] | None:
        payload = self._read()
        versions = payload.get("versions", [])
        target: dict[str, Any] | None = None
        kept_versions: list[dict[str, Any]] = []
        for item in versions:
            if target is None and str(item.get("id") or "") == version_id:
                target = dict(item)
                continue
            kept_versions.append(item)
        if target is None:
            return None

        payload["versions"] = kept_versions
        doc_id = str(target.get("doc_id") or "")
        if doc_id:
            has_other = any(str(v.get("doc_id") or "") == doc_id for v in kept_versions)
            if not has_other:
                payload["documents"] = [d for d in payload.get("documents", []) if str(d.get("id") or "") != doc_id]
        self._write(payload)
        return target


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
                        content_hash VARCHAR(128),
                        mineru_json_key VARCHAR(1024),
                        mineru_md_key VARCHAR(1024),
                        notes TEXT,
                        created_at TIMESTAMP NOT NULL DEFAULT now()
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    ALTER TABLE document_versions
                    ADD COLUMN IF NOT EXISTS content_hash VARCHAR(128)
                    """
                )
            )
            conn.execute(
                text(
                    """
                    ALTER TABLE document_versions
                    ADD COLUMN IF NOT EXISTS mineru_json_key VARCHAR(1024)
                    """
                )
            )
            conn.execute(
                text(
                    """
                    ALTER TABLE document_versions
                    ADD COLUMN IF NOT EXISTS mineru_md_key VARCHAR(1024)
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
                    INSERT INTO document_versions (id, doc_id, version_no, storage_key, status, content_hash, created_at)
                    VALUES (:id, :doc_id, :version_no, :storage_key, :status, :content_hash, now())
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "id": version["id"],
                    "doc_id": version["doc_id"],
                    "version_no": int(version.get("version_no", 1)),
                    "storage_key": version["storage_key"],
                    "status": version.get("status", "uploaded"),
                    "content_hash": version.get("content_hash"),
                },
            )

    def list_versions(
        self,
        statuses: list[str] | None = None,
        limit: int | None = None,
        doc_type: str | None = None,
    ) -> list[dict[str, Any]]:
        self._ensure_schema()
        query = (
            "SELECT v.id, v.doc_id, v.storage_key, v.status, v.content_hash, v.notes, v.created_at, "
            "d.doc_type "
            "FROM document_versions v "
            "LEFT JOIN documents d ON d.id = v.doc_id"
        )
        params: dict[str, Any] = {}
        where_clauses: list[str] = []

        if statuses:
            placeholders = []
            for idx, status in enumerate(statuses):
                key = f"status_{idx}"
                placeholders.append(f":{key}")
                params[key] = status
            where_clauses.append(f"v.status IN ({','.join(placeholders)})")
        if doc_type:
            params["doc_type"] = str(doc_type).strip()
            where_clauses.append("COALESCE(d.doc_type, '') = :doc_type")
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        query += " ORDER BY v.created_at DESC"
        if limit is not None:
            query += " LIMIT :limit"
            params["limit"] = int(limit)

        with self.engine.begin() as conn:
            rows = conn.execute(text(query), params).mappings().all()

        out: list[dict[str, Any]] = []
        for row in rows:
            notes = row.get("notes")
            if isinstance(notes, str):
                try:
                    notes = json.loads(notes)
                except json.JSONDecodeError:
                    notes = {"raw": notes}
            out.append(
                {
                    "id": row.get("id"),
                    "doc_id": row.get("doc_id"),
                    "storage_key": row.get("storage_key"),
                    "status": row.get("status"),
                    "doc_type": row.get("doc_type"),
                    "content_hash": row.get("content_hash"),
                    "notes": notes,
                    "created_at": str(row.get("created_at")),
                }
            )
        return out

    def update_version_status(self, version_id: str, status: str, notes: dict[str, Any] | None = None) -> None:
        self._ensure_schema()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE document_versions
                    SET status=:status, notes=:notes
                    WHERE id=:version_id
                    """
                ),
                {
                    "status": status,
                    "notes": json.dumps(notes, ensure_ascii=False) if notes is not None else None,
                    "version_id": version_id,
                },
            )

    def delete_version(self, version_id: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, doc_id, storage_key, content_hash, mineru_json_key, mineru_md_key, notes
                    FROM document_versions
                    WHERE id=:version_id
                    """
                ),
                {"version_id": version_id},
            ).mappings().first()
            if row is None:
                return None

            conn.execute(
                text(
                    """
                    DELETE FROM document_versions
                    WHERE id=:version_id
                    """
                ),
                {"version_id": version_id},
            )
            conn.execute(
                text(
                    """
                    DELETE FROM documents d
                    WHERE d.id=:doc_id
                      AND NOT EXISTS (
                        SELECT 1
                        FROM document_versions v
                        WHERE v.doc_id = d.id
                      )
                    """
                ),
                {"doc_id": row.get("doc_id")},
            )
            return dict(row)


def build_doc_registry_from_env() -> DocRegistry:
    backend = os.getenv("DOC_REGISTRY_BACKEND", "auto").lower()
    if backend == "json":
        return JSONDocRegistry(Path(os.getenv("DOC_REGISTRY_PATH", ".runtime/registry.json")))

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return SQLDocRegistry(database_url)

    return JSONDocRegistry(Path(os.getenv("DOC_REGISTRY_PATH", ".runtime/registry.json")))
