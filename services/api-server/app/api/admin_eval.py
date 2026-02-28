"""Admin evaluation APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.services.auth import ROLE_SYSTEM_ADMIN, require_roles
from app.services.eval_dataset import add_sample_to_dataset, ensure_dataset_layout
from app.services.eval_executor import execute_eval_run
from app.services.eval_repo import build_eval_repo_from_env

router = APIRouter(
    prefix="/api/admin/eval",
    tags=["admin-eval"],
    dependencies=[Depends(require_roles([ROLE_SYSTEM_ADMIN]))],
)
EVAL_REPO = build_eval_repo_from_env()


@router.get("/runs")
def list_runs() -> dict:
    return {"items": EVAL_REPO.list_runs()}


@router.get("/results")
def list_results() -> dict:
    return {"items": EVAL_REPO.list_results()}


@router.get("/results/{result_id}")
def get_result_detail(result_id: str) -> dict:
    item = EVAL_REPO.get_result(result_id=result_id)
    if item is None:
        raise HTTPException(status_code=404, detail="eval result not found")
    return {"item": item}


@router.post("/datasets/add")
def add_dataset_sample(payload: dict) -> dict:
    dataset_version = str(payload.get("dataset_version") or "v1.0")
    doc_id = str(payload.get("doc_id") or "")
    version_id = str(payload.get("version_id") or "")
    question = str(payload.get("question") or "").strip()
    truth_answer = str(payload.get("truth_answer") or "").strip()
    task_type = str(payload.get("task_type") or "QA").upper()

    if not question:
        raise HTTPException(status_code=400, detail="question is required")
    if not truth_answer:
        raise HTTPException(status_code=400, detail="truth_answer is required")

    ensure_dataset_layout(dataset_version)
    item = add_sample_to_dataset(
        dataset_version=dataset_version,
        doc_id=doc_id,
        version_id=version_id,
        question=question,
        truth_answer=truth_answer,
        task_type=task_type,
    )
    return {"item": item}


@router.post("/runs/start")
def start_eval_run(payload: dict | None = None) -> dict:
    req = payload or {}
    dataset_version = str(req.get("dataset_version") or "v1.0")
    run = EVAL_REPO.create_run(dataset_version=dataset_version, status="running")
    summary = execute_eval_run(repo=EVAL_REPO, run_id=run["id"], dataset_version=dataset_version)
    return {"run": run, "summary": summary}


@router.get("/trends")
def eval_trends() -> dict:
    return {"item": EVAL_REPO.build_trends()}
