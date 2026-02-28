"""Worker-side document status updates."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import create_engine, text


class DocStatusRegistry(Protocol):
    def mark_version_status(self, version_id: str, status: str, notes: dict[str, Any] | None = None) -> None:
        raise NotImplementedError


class SQLDocStatusRegistry:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)

    def mark_version_status(self, version_id: str, status: str, notes: dict[str, Any] | None = None) -> None:
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
                    "notes": json.dumps(notes or {}, ensure_ascii=False),
                    "version_id": version_id,
                },
            )


class JsonDocStatusRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path

    def mark_version_status(self, version_id: str, status: str, notes: dict[str, Any] | None = None) -> None:
        if not self.path.exists():
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        for version in payload.get("versions", []):
            if version.get("id") == version_id:
                version["status"] = status
                version["notes"] = notes or {}
                break
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_doc_status_registry_from_env() -> DocStatusRegistry:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return SQLDocStatusRegistry(database_url)
    return JsonDocStatusRegistry(Path(os.getenv("DOC_REGISTRY_PATH", ".runtime/registry.json")))
