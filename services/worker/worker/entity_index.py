"""Persistent entity index (SQL/JSON backends)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol
from uuid import uuid5, NAMESPACE_DNS

from sqlalchemy import create_engine, text


class EntityIndex(Protocol):
    def get_or_create_id(self, kind: str, name: str) -> str:
        raise NotImplementedError


class JsonEntityIndex:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("{}", encoding="utf-8")

    def _read(self) -> dict[str, str]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, payload: dict[str, str]) -> None:
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_or_create_id(self, kind: str, name: str) -> str:
        norm_kind = str(kind).strip().lower() or "unknown"
        norm_name = str(name).strip()
        key = f"{norm_kind}:{norm_name}"

        payload = self._read()
        if key in payload:
            return payload[key]

        stable = str(uuid5(NAMESPACE_DNS, key)).replace("-", "")[:16]
        entity_id = f"{norm_kind}_{stable}"
        payload[key] = entity_id
        self._write(payload)
        return entity_id


class SQLEntityIndex:
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
                    CREATE TABLE IF NOT EXISTS entity_dictionary (
                        id VARCHAR(64) PRIMARY KEY,
                        entity_kind VARCHAR(32) NOT NULL,
                        entity_name VARCHAR(512) NOT NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT now(),
                        UNIQUE(entity_kind, entity_name)
                    )
                    """
                )
            )
        self._schema_ready = True

    def get_or_create_id(self, kind: str, name: str) -> str:
        self._ensure_schema()
        norm_kind = str(kind).strip().lower() or "unknown"
        norm_name = str(name).strip()
        stable = str(uuid5(NAMESPACE_DNS, f"{norm_kind}:{norm_name}")).replace("-", "")[:16]
        entity_id = f"{norm_kind}_{stable}"

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO entity_dictionary (id, entity_kind, entity_name, created_at)
                    VALUES (:id, :entity_kind, :entity_name, now())
                    ON CONFLICT (entity_kind, entity_name) DO NOTHING
                    """
                ),
                {
                    "id": entity_id,
                    "entity_kind": norm_kind,
                    "entity_name": norm_name,
                },
            )

            row = conn.execute(
                text(
                    """
                    SELECT id FROM entity_dictionary
                    WHERE entity_kind=:entity_kind AND entity_name=:entity_name
                    """
                ),
                {
                    "entity_kind": norm_kind,
                    "entity_name": norm_name,
                },
            ).first()

        if row is not None:
            return str(row[0])
        return entity_id


def build_entity_index_from_env() -> EntityIndex:
    backend = os.getenv("ENTITY_INDEX_BACKEND", "auto").lower()

    if backend == "json":
        return JsonEntityIndex(Path(os.getenv("ENTITY_INDEX_PATH", ".runtime/entity-index.json")))

    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return SQLEntityIndex(database_url)

    return JsonEntityIndex(Path(os.getenv("ENTITY_INDEX_PATH", ".runtime/entity-index.json")))
