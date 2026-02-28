"""Evaluation run/result repository for admin APIs."""

from __future__ import annotations

import os
from statistics import mean
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import create_engine, text


class EvalRepo(Protocol):
    def list_runs(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def list_results(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get_result(self, result_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def create_run(self, dataset_version: str, status: str = "queued") -> dict[str, Any]:
        raise NotImplementedError

    def update_run_status(self, run_id: str, status: str) -> None:
        raise NotImplementedError

    def add_results(self, run_id: str, results: list[dict[str, Any]]) -> None:
        raise NotImplementedError

    def build_trends(self) -> dict[str, Any]:
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

    def create_run(self, dataset_version: str, status: str = "queued") -> dict[str, Any]:
        run = {
            "id": f"run_{uuid4().hex[:12]}",
            "dataset_version": dataset_version,
            "status": status,
        }
        self.runs.insert(0, run)
        return dict(run)

    def update_run_status(self, run_id: str, status: str) -> None:
        for item in self.runs:
            if item.get("id") == run_id:
                item["status"] = status
                break

    def add_results(self, run_id: str, results: list[dict[str, Any]]) -> None:
        for item in results:
            row = {
                "id": str(item.get("id") or f"res_{uuid4().hex[:12]}"),
                "run_id": run_id,
                "sample_id": item.get("sample_id"),
                "provider": item.get("provider", "stub"),
                "model": item.get("model", "stub-mvp"),
                "score_total": float(item.get("score_total", 0.0)),
                "breakdown_json": item.get("breakdown_json", {}),
                "output_path": item.get("output_path", ""),
                "diff_path": item.get("diff_path", ""),
            }
            self.results.insert(0, row)

    def build_trends(self) -> dict[str, Any]:
        scores = [float(x.get("score_total", 0.0)) for x in self.results]
        fail_count = sum(1 for x in scores if x < 60)
        total = len(scores)
        return {
            "total_results": total,
            "failed_results": fail_count,
            "failure_rate": (fail_count / total) if total else 0.0,
            "quality_score_avg": mean(scores) if scores else 0.0,
        }


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

    def create_run(self, dataset_version: str, status: str = "queued") -> dict[str, Any]:
        self._ensure_schema()
        run = {
            "id": f"run_{uuid4().hex[:12]}",
            "dataset_version": dataset_version,
            "status": status,
        }
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO eval_run (id, dataset_version, status, created_at)
                    VALUES (:id, :dataset_version, :status, now())
                    """
                ),
                run,
            )
        return run

    def update_run_status(self, run_id: str, status: str) -> None:
        self._ensure_schema()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE eval_run
                    SET status=:status
                    WHERE id=:id
                    """
                ),
                {"id": run_id, "status": status},
            )

    def add_results(self, run_id: str, results: list[dict[str, Any]]) -> None:
        self._ensure_schema()
        with self.engine.begin() as conn:
            for item in results:
                conn.execute(
                    text(
                        """
                        INSERT INTO eval_result (
                            id, run_id, sample_id, provider, model, score_total,
                            breakdown_json, output_path, diff_path, created_at
                        ) VALUES (
                            :id, :run_id, :sample_id, :provider, :model, :score_total,
                            :breakdown_json, :output_path, :diff_path, now()
                        )
                        """
                    ),
                    {
                        "id": str(item.get("id") or f"res_{uuid4().hex[:12]}"),
                        "run_id": run_id,
                        "sample_id": str(item.get("sample_id", "unknown")),
                        "provider": str(item.get("provider", "stub")),
                        "model": str(item.get("model", "stub-mvp")),
                        "score_total": float(item.get("score_total", 0.0)),
                        "breakdown_json": item.get("breakdown_json", {}),
                        "output_path": str(item.get("output_path", "")),
                        "diff_path": str(item.get("diff_path", "")),
                    },
                )

    def build_trends(self) -> dict[str, Any]:
        self._ensure_schema()
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT COUNT(*) AS total,
                           SUM(CASE WHEN score_total < 60 THEN 1 ELSE 0 END) AS failed,
                           COALESCE(AVG(score_total), 0) AS quality_score_avg
                    FROM eval_result
                    """
                )
            ).mappings().first()

        total = int((row or {}).get("total") or 0)
        failed = int((row or {}).get("failed") or 0)
        avg_score = float((row or {}).get("quality_score_avg") or 0.0)
        return {
            "total_results": total,
            "failed_results": failed,
            "failure_rate": (failed / total) if total else 0.0,
            "quality_score_avg": avg_score,
        }


def build_eval_repo_from_env() -> EvalRepo:
    backend = os.getenv("EVAL_REPO_BACKEND", "auto").lower()
    if backend == "memory":
        return InMemoryEvalRepo()

    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return SQLEvalRepo(database_url)

    return InMemoryEvalRepo()
