"""Document artifact repository for admin inspection APIs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import create_engine, text


class ArtifactRepo(Protocol):
    def get_version_artifacts(self, version_id: str) -> dict[str, Any] | None:
        raise NotImplementedError


def _normalize_notes(notes: Any) -> dict[str, Any]:
    if isinstance(notes, dict):
        return notes
    if isinstance(notes, str):
        try:
            parsed = json.loads(notes)
            if isinstance(parsed, dict):
                return parsed
            return {"raw": parsed}
        except json.JSONDecodeError:
            return {"raw": notes}
    return {}


class JSONArtifactRepo:
    def __init__(self, registry_path: Path, assets_path: Path) -> None:
        self.registry_path = registry_path
        self.assets_path = assets_path

    def _read_registry(self) -> dict[str, Any]:
        if not self.registry_path.exists():
            return {"documents": [], "versions": []}
        return json.loads(self.registry_path.read_text(encoding="utf-8"))

    def _read_assets(self, version_id: str) -> list[dict[str, Any]]:
        if not self.assets_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.assets_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("version_id") == version_id:
                rows.append(item)
        return rows

    def get_version_artifacts(self, version_id: str) -> dict[str, Any] | None:
        payload = self._read_registry()
        version = next((v for v in payload.get("versions", []) if v.get("id") == version_id), None)
        if version is None:
            return None

        assets = self._read_assets(version_id=version_id)
        notes = _normalize_notes(version.get("notes"))
        return {
            "version": version,
            "assets": assets,
            "intermediate": {
                "status": version.get("status"),
                "storage_key": version.get("storage_key"),
                "notes": notes,
                "asset_count": len(assets),
            },
        }


class SQLArtifactRepo:
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
                    CREATE TABLE IF NOT EXISTS document_versions (
                        id VARCHAR(64) PRIMARY KEY,
                        doc_id VARCHAR(64) NOT NULL,
                        version_no INTEGER NOT NULL,
                        storage_key VARCHAR(1024) NOT NULL,
                        status VARCHAR(64) NOT NULL,
                        notes TEXT,
                        created_at TIMESTAMP NOT NULL DEFAULT now()
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS assets (
                        id VARCHAR(64) PRIMARY KEY,
                        doc_id VARCHAR(64) NOT NULL,
                        version_id VARCHAR(64) NOT NULL,
                        asset_type VARCHAR(64) NOT NULL,
                        data_json JSON NOT NULL,
                        source_page INTEGER NOT NULL,
                        source_excerpt TEXT NOT NULL,
                        source_type VARCHAR(32) NOT NULL,
                        block_id VARCHAR(64),
                        table_id VARCHAR(64),
                        row_index INTEGER,
                        created_at TIMESTAMP NOT NULL DEFAULT now()
                    )
                    """
                )
            )
        self._schema_ready = True

    def get_version_artifacts(self, version_id: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, doc_id, storage_key, status, notes, created_at
                    FROM document_versions
                    WHERE id=:version_id
                    """
                ),
                {"version_id": version_id},
            ).mappings().first()
            if row is None:
                return None

            asset_rows = conn.execute(
                text(
                    """
                    SELECT id, doc_id, version_id, asset_type, data_json, source_page, source_excerpt,
                           source_type, block_id, table_id, row_index, created_at
                    FROM assets
                    WHERE version_id=:version_id
                    ORDER BY created_at DESC
                    """
                ),
                {"version_id": version_id},
            ).mappings().all()

        version = {
            "id": row.get("id"),
            "doc_id": row.get("doc_id"),
            "storage_key": row.get("storage_key"),
            "status": row.get("status"),
            "notes": _normalize_notes(row.get("notes")),
            "created_at": str(row.get("created_at")),
        }
        assets = [dict(item) for item in asset_rows]
        return {
            "version": version,
            "assets": assets,
            "intermediate": {
                "status": version["status"],
                "storage_key": version["storage_key"],
                "notes": version["notes"],
                "asset_count": len(assets),
            },
        }


def build_artifact_repo_from_env() -> ArtifactRepo:
    backend = os.getenv("ARTIFACT_REPO_BACKEND", "auto").lower()
    if backend == "json":
        return JSONArtifactRepo(
            registry_path=Path(os.getenv("DOC_REGISTRY_PATH", ".runtime/registry.json")),
            assets_path=Path(os.getenv("ASSET_JSONL_PATH", ".runtime/assets.jsonl")),
        )

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return SQLArtifactRepo(database_url)

    return JSONArtifactRepo(
        registry_path=Path(os.getenv("DOC_REGISTRY_PATH", ".runtime/registry.json")),
        assets_path=Path(os.getenv("ASSET_JSONL_PATH", ".runtime/assets.jsonl")),
    )
