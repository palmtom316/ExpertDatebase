"""Execute eval runs and persist artifacts/results."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.services.eval_dataset import load_dataset_rows
from app.services.eval_repo import EvalRepo
from app.services.llm_router import LLMRouter
from app.services.storage import build_storage_from_env


def _score_qa(pred: str, truth: str) -> tuple[float, dict[str, Any]]:
    pred_text = pred.strip()
    truth_text = truth.strip()
    hit = 1.0 if truth_text and truth_text in pred_text else 0.0
    cite_presence = 1.0 if "引用" in pred_text or "证据" in pred_text else 0.5
    score = 20 * cite_presence + 80 * hit
    return score, {
        "cite_presence": cite_presence,
        "exact_hit": hit,
    }


def _result_output_dir(run_id: str) -> Path:
    root = Path(os.getenv("EVAL_OUTPUTS_ROOT", "outputs"))
    path = root / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def execute_eval_run(repo: EvalRepo, run_id: str, dataset_version: str) -> dict[str, Any]:
    rows = load_dataset_rows(dataset_version)
    output_dir = _result_output_dir(run_id)
    storage = build_storage_from_env()

    router = LLMRouter()
    results: list[dict[str, Any]] = []

    for row in rows:
        sample_id = row["sample_id"]
        task_type = str(row.get("task_type") or "QA").upper()

        question = str((row.get("input") or {}).get("question") or "")
        truth_answer = str((row.get("truth") or {}).get("answer") or "")

        llm = router.route_and_generate(task_type="qa_generate", prompt=question)
        pred_text = llm.get("text", "")

        score_total, breakdown = _score_qa(pred_text, truth_answer)
        diff = {
            "qa": {
                "truth": truth_answer,
                "pred": pred_text,
                "match": score_total >= 80,
            },
            "ie": {},
            "table": {},
            "retrieval": {},
        }

        pred_payload = {
            "sample_id": sample_id,
            "task_type": task_type,
            "provider": llm.get("provider"),
            "model": llm.get("model"),
            "pred": pred_text,
            "truth": truth_answer,
        }
        diff_payload = {
            "run_id": run_id,
            "sample_id": sample_id,
            "task_type": task_type,
            "score_total": score_total,
            "breakdown": breakdown,
            "diff": diff,
        }

        pred_path = output_dir / f"{sample_id}.pred.json"
        diff_path = output_dir / f"{sample_id}.diff.json"
        pred_path.write_text(json.dumps(pred_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        diff_path.write_text(json.dumps(diff_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        storage.put_bytes(
            f"eval/{run_id}/{pred_path.name}",
            pred_path.read_bytes(),
            content_type="application/json",
        )
        storage.put_bytes(
            f"eval/{run_id}/{diff_path.name}",
            diff_path.read_bytes(),
            content_type="application/json",
        )

        results.append(
            {
                "id": f"res_{uuid4().hex[:12]}",
                "sample_id": sample_id,
                "provider": llm.get("provider", "stub"),
                "model": llm.get("model", "stub-mvp"),
                "score_total": score_total,
                "breakdown_json": breakdown,
                "output_path": str(pred_path),
                "diff_path": str(diff_path),
            }
        )

    repo.add_results(run_id=run_id, results=results)
    repo.update_run_status(run_id=run_id, status="completed")

    return {
        "run_id": run_id,
        "dataset_version": dataset_version,
        "result_count": len(results),
        "output_dir": str(output_dir),
    }
