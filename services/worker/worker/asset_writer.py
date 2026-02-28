"""Asset persistence adapters (JSONL/SQL backends)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import JSON, bindparam, create_engine, text


class JsonlAssetWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, assets: list[dict[str, Any]]) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            for item in assets:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")


class AssetRepo(Protocol):
    def write_assets(self, doc_id: str, version_id: str, assets: list[dict[str, Any]]) -> int:
        raise NotImplementedError


class JsonlAssetRepo:
    def __init__(self, path: Path) -> None:
        self.writer = JsonlAssetWriter(path)

    def write_assets(self, doc_id: str, version_id: str, assets: list[dict[str, Any]]) -> int:
        rows: list[dict[str, Any]] = []
        for item in assets:
            rows.append(
                {
                    "id": f"ast_{uuid4().hex[:12]}",
                    "doc_id": doc_id,
                    "version_id": version_id,
                    **item,
                }
            )
        self.writer.write(rows)
        return len(rows)


class SQLAssetRepo:
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

    def write_assets(self, doc_id: str, version_id: str, assets: list[dict[str, Any]]) -> int:
        self._ensure_schema()
        if not assets:
            return 0

        insert_stmt = text(
            """
            INSERT INTO assets (
                id, doc_id, version_id, asset_type, data_json, source_page,
                source_excerpt, source_type, block_id, table_id, row_index, created_at
            ) VALUES (
                :id, :doc_id, :version_id, :asset_type, :data_json, :source_page,
                :source_excerpt, :source_type, :block_id, :table_id, :row_index, now()
            )
            """
        ).bindparams(bindparam("data_json", type_=JSON))

        with self.engine.begin() as conn:
            for item in assets:
                conn.execute(
                    insert_stmt,
                    {
                        "id": f"ast_{uuid4().hex[:12]}",
                        "doc_id": doc_id,
                        "version_id": version_id,
                        "asset_type": item.get("asset_type", "unknown"),
                        "data_json": item.get("data_json", {}),
                        "source_page": int(item.get("source_page", 0) or 0),
                        "source_excerpt": str(item.get("source_excerpt", "")),
                        "source_type": str(item.get("source_type", "chapter_text")),
                        "block_id": item.get("block_id"),
                        "table_id": item.get("table_id"),
                        "row_index": item.get("row_index"),
                    },
                )
        return len(assets)


def build_asset_repo_from_env() -> AssetRepo:
    backend = os.getenv("ASSET_REPO_BACKEND", "auto").lower()
    if backend == "json":
        return JsonlAssetRepo(Path(os.getenv("ASSET_JSONL_PATH", ".runtime/assets.jsonl")))

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return SQLAssetRepo(database_url)

    return JsonlAssetRepo(Path(os.getenv("ASSET_JSONL_PATH", ".runtime/assets.jsonl")))
