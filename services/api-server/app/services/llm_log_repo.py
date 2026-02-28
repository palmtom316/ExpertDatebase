"""LLM call log repository (memory/SQL backends)."""

from __future__ import annotations

import os
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import JSON, bindparam, create_engine, text


class LLMLogRepo(Protocol):
    def add_log(self, record: dict[str, Any]) -> None:
        raise NotImplementedError


class InMemoryLLMLogRepo:
    def __init__(self) -> None:
        self.logs: list[dict[str, Any]] = []

    def add_log(self, record: dict[str, Any]) -> None:
        self.logs.append(dict(record))


class SQLLLMLogRepo:
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
                    CREATE TABLE IF NOT EXISTS llm_call_log (
                        id VARCHAR(64) PRIMARY KEY,
                        request_id VARCHAR(64) NOT NULL,
                        task_type VARCHAR(64) NOT NULL,
                        provider VARCHAR(64) NOT NULL,
                        model VARCHAR(128) NOT NULL,
                        latency_ms INTEGER,
                        tokens_in INTEGER,
                        tokens_out INTEGER,
                        error TEXT,
                        metadata_json JSON NOT NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT now()
                    )
                    """
                )
            )
        self._schema_ready = True

    def add_log(self, record: dict[str, Any]) -> None:
        self._ensure_schema()
        insert_stmt = text(
            """
            INSERT INTO llm_call_log (
                id, request_id, task_type, provider, model, latency_ms, tokens_in, tokens_out,
                error, metadata_json, created_at
            ) VALUES (
                :id, :request_id, :task_type, :provider, :model, :latency_ms, :tokens_in, :tokens_out,
                :error, :metadata_json, now()
            )
            """
        ).bindparams(bindparam("metadata_json", type_=JSON))

        with self.engine.begin() as conn:
            conn.execute(
                insert_stmt,
                {
                    "id": str(record.get("id") or f"llm_{uuid4().hex[:12]}"),
                    "request_id": str(record.get("request_id") or f"req_{uuid4().hex[:12]}"),
                    "task_type": str(record.get("task_type", "unknown")),
                    "provider": str(record.get("provider", "unknown")),
                    "model": str(record.get("model", "unknown")),
                    "latency_ms": record.get("latency_ms"),
                    "tokens_in": record.get("tokens_in"),
                    "tokens_out": record.get("tokens_out"),
                    "error": record.get("error"),
                    "metadata_json": record.get("metadata_json", {}),
                },
            )


def build_llm_log_repo_from_env() -> LLMLogRepo:
    backend = os.getenv("LLM_LOG_REPO_BACKEND", "auto").lower()
    if backend == "memory":
        return InMemoryLLMLogRepo()

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return SQLLLMLogRepo(database_url)

    return InMemoryLLMLogRepo()
