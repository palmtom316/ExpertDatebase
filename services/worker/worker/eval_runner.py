"""Offline evaluation runner (MVP)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from worker.diff_report import make_diff_report
from worker.scorer import score_ie, score_qa, score_retrieval, score_table


def run_eval_samples(
    run_id: str,
    samples: list[dict[str, Any]],
    predictor: Callable[[dict[str, Any]], dict[str, Any]],
    output_dir: Path,
) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    for sample in samples:
        pred = predictor(sample)
        task_type = sample["task_type"]

        if task_type.startswith("IE"):
            total = score_ie(**sample["metrics"])
        elif task_type.startswith("TABLE"):
            total = score_table(**sample["metrics"])
        elif task_type.startswith("QA"):
            total = score_qa(**sample["metrics"])
        else:
            total = score_retrieval(**sample["metrics"])

        report = make_diff_report(
            run_id=run_id,
            sample_id=sample["sample_id"],
            task_type=task_type,
            provider=pred.get("provider", "MVP"),
            model=pred.get("model", "MVP"),
            score_total=total,
            breakdown=sample["metrics"],
            diff={"truth": sample.get("truth", {}), "pred": pred.get("pred", {})},
        )

        pred_path = output_dir / f"{sample['sample_id']}.pred.json"
        diff_path = output_dir / f"{sample['sample_id']}.diff.json"
        pred_path.write_text(json.dumps(pred, ensure_ascii=False, indent=2), encoding="utf-8")
        diff_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        results.append(
            {
                "sample_id": sample["sample_id"],
                "task_type": task_type,
                "score_total": total,
                "output_path": str(pred_path),
                "diff_path": str(diff_path),
            }
        )

    return results
