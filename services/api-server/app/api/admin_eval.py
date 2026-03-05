"""Admin evaluation APIs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.services.auth import ROLE_SYSTEM_ADMIN, require_roles
from app.services.eval_dataset import add_sample_to_dataset, ensure_dataset_layout
from app.services.eval_executor import execute_eval_run
from app.services.eval_repo import build_eval_repo_from_env
from app.services.entity_index import build_entity_index_from_env
from app.services.retrieval_eval import evaluate_retrieval_samples
from app.services.search_service import create_search_repo_from_env, hybrid_search

router = APIRouter(
    prefix="/api/admin/eval",
    tags=["admin-eval"],
    dependencies=[Depends(require_roles([ROLE_SYSTEM_ADMIN]))],
)
EVAL_REPO = build_eval_repo_from_env()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        obj = json.loads(raw)
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


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
    runtime_config = {
        "llm_provider": str(req.get("llm_provider") or "").strip().lower(),
        "llm_api_key": str(req.get("llm_api_key") or "").strip(),
        "llm_model": str(req.get("llm_model") or "").strip(),
        "llm_base_url": str(req.get("llm_base_url") or "").strip(),
    }
    runtime_config = {k: v for k, v in runtime_config.items() if v}
    run = EVAL_REPO.create_run(dataset_version=dataset_version, status="running")
    summary = execute_eval_run(
        repo=EVAL_REPO,
        run_id=run["id"],
        dataset_version=dataset_version,
        runtime_config=runtime_config,
    )
    return {"run": run, "summary": summary}


@router.get("/trends")
def eval_trends() -> dict:
    return {"item": EVAL_REPO.build_trends()}


@router.get("/llm-quality")
def llm_quality() -> dict:
    items = EVAL_REPO.list_results()
    scores = [float(x.get("score_total", 0.0)) for x in items]
    avg = (sum(scores) / len(scores)) if scores else 0.0
    grade = "A" if avg >= 85 else ("B" if avg >= 65 else "C")
    return {
        "item": {
            "overall_score": avg,
            "grade": grade,
            "result_count": len(scores),
            "recent_results": items[:20],
        }
    }


@router.post("/retrieval/run")
def run_retrieval_eval(payload: dict | None = None) -> dict:
    req = payload or {}
    dataset_path_raw = str(req.get("dataset_path") or "").strip()
    top_k = max(1, int(req.get("top_k") or 10))
    if dataset_path_raw:
        dataset_path = Path(dataset_path_raw).expanduser().resolve()
    else:
        dataset_path = Path("datasets/v1.0/retrieval_eval.jsonl").resolve()
    if not dataset_path.exists():
        raise HTTPException(status_code=404, detail=f"retrieval dataset not found: {dataset_path}")

    samples = _read_jsonl(dataset_path)
    if not samples:
        raise HTTPException(status_code=400, detail="retrieval dataset is empty")

    runtime_config = {
        "embedding_provider": str(req.get("embedding_provider") or "").strip().lower(),
        "embedding_api_key": str(req.get("embedding_api_key") or "").strip(),
        "embedding_model": str(req.get("embedding_model") or "").strip(),
        "embedding_base_url": str(req.get("embedding_base_url") or "").strip(),
        "rerank_provider": str(req.get("rerank_provider") or "").strip().lower(),
        "rerank_api_key": str(req.get("rerank_api_key") or "").strip(),
        "rerank_model": str(req.get("rerank_model") or "").strip(),
        "rerank_base_url": str(req.get("rerank_base_url") or "").strip(),
    }
    runtime_config = {k: v for k, v in runtime_config.items() if v}

    repo = create_search_repo_from_env()
    entity_index = build_entity_index_from_env()
    debug_rows: list[dict[str, Any]] = []

    def _search(sample: dict[str, Any]) -> list[dict[str, Any]]:
        query = str(sample.get("query") or "").strip()
        if not query:
            debug_rows.append({"query": "", "route_counts": {}, "degraded_routes": {}})
            return []
        must: list[dict[str, Any]] = []
        selected_doc_id = str(sample.get("selected_doc_id") or "").strip()
        selected_version_id = str(sample.get("selected_version_id") or "").strip()
        if selected_doc_id:
            must.append({"key": "doc_id", "match": {"value": selected_doc_id}})
        if selected_version_id:
            must.append({"key": "version_id", "match": {"value": selected_version_id}})
        search_filter = {"must": must} if must else None

        res = hybrid_search(
            question=query,
            repo=repo,
            entity_index=entity_index,
            top_k=top_k,
            runtime_config=runtime_config or None,
            search_filter=search_filter,
        )
        debug = res.get("debug") if isinstance(res, dict) else {}
        debug_rows.append(
            {
                "query": query,
                "route_counts": (debug or {}).get("route_counts") or {},
                "degraded_routes": (debug or {}).get("degraded_routes") or {},
                "embedding": (debug or {}).get("embedding") or {},
            }
        )
        return res.get("hits") or []

    result = evaluate_retrieval_samples(samples=samples, search_fn=_search, top_k=top_k)
    result["dataset"] = str(dataset_path)
    result["allow_traffic"] = bool((result.get("release_gate") or {}).get("passed"))
    result["search_debug"] = debug_rows
    return {"item": result}
