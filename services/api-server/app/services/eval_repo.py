"""Evaluation run/result repository for admin APIs."""

from __future__ import annotations

import os
from typing import Any, Protocol

from sqlalchemy import create_engine, text


class EvalRepo(Protocol):
    def list_runs(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def list_results(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get_result(self, result_id: str) -> dict[str, Any] | None:
        raise NotImplementedError


class InMemoryEvalRepo:
    def __init__(self) -> None:
        self.runs: list[dict[str, Any]] = []
        self.results: list[dict[str, Any]] = []

    def list_runs(self) -> list[dict[str, Any]]:
        return list(self.runs)

    def list_results(self) -> list[dict[str, Any]]:
        return list(self.results)

    def get_result(self, result_id: str) -> dict[str, Any] | None:
        for item in self.results:
            if item.get("id") == result_id:
                return dict(item)
        return None


class SQLEvalRepo:
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
                    CREATE TABLE IF NOT EXISTS eval_run (
                        id VARCHAR(64) PRIMARY KEY,
                        dataset_version VARCHAR(64) NOT NULL,
                        status VARCHAR(32) NOT NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT now()
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS eval_result (
                        id VARCHAR(64) PRIMARY KEY,
                        run_id VARCHAR(64) NOT NULL,
                        sample_id VARCHAR(64) NOT NULL,
                        provider VARCHAR(64) NOT NULL,
                        model VARCHAR(128) NOT NULL,
                        score_total FLOAT NOT NULL,
                        breakdown_json JSON NOT NULL,
                        output_path VARCHAR(1024) NOT NULL,
                        diff_path VARCHAR(1024) NOT NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT now()
                    )
                    """
                )
            )
        self._schema_ready = True

    def list_runs(self) -> list[dict[str, Any]]:
        self._ensure_schema()
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, dataset_version, status, created_at
                    FROM eval_run
                    ORDER BY created_at DESC
                    LIMIT 200
                    """
                )
            ).mappings().all()
        return [dict(row) for row in rows]

    def list_results(self) -> list[dict[str, Any]]:
        self._ensure_schema()
        with self.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, run_id, sample_id, provider, model, score_total, breakdown_json,
                           output_path, diff_path, created_at
                    FROM eval_result
                    ORDER BY created_at DESC
                    LIMIT 500
                    """
                )
            ).mappings().all()
        return [dict(row) for row in rows]

    def get_result(self, result_id: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, run_id, sample_id, provider, model, score_total, breakdown_json,
                           output_path, diff_path, created_at
                    FROM eval_result
                    WHERE id=:result_id
                    """
                ),
                {"result_id": result_id},
            ).mappings().first()
        if row is None:
            return None
        return dict(row)


def build_eval_repo_from_env() -> EvalRepo:
    backend = os.getenv("EVAL_REPO_BACKEND", "auto").lower()
    if backend == "memory":
        return InMemoryEvalRepo()

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return SQLEvalRepo(database_url)

    return InMemoryEvalRepo()
