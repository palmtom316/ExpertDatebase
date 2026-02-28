"""Diff report formatter."""

from __future__ import annotations

from typing import Any


def make_diff_report(
    run_id: str,
    sample_id: str,
    task_type: str,
    provider: str,
    model: str,
    score_total: float,
    breakdown: dict[str, Any],
    diff: dict[str, Any],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "sample_id": sample_id,
        "task_type": task_type,
        "provider": provider,
        "model": model,
        "score_total": score_total,
        "breakdown": breakdown,
        "errors": [],
        "diff": diff,
    }
