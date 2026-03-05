"""Admin job control APIs: cleanup failed and retry failed."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.auth import ROLE_SYSTEM_ADMIN, require_roles
from app.services.doc_registry import build_doc_registry_from_env
from app.services.retry_service import cleanup_failed_versions, list_failed_versions, reprocess_version, retry_failed_versions
from app.services.task_queue import build_task_queue_from_env

router = APIRouter(
    prefix="/api/admin/jobs",
    tags=["admin-jobs"],
    dependencies=[Depends(require_roles([ROLE_SYSTEM_ADMIN]))],
)

REGISTRY = build_doc_registry_from_env()
TASK_QUEUE = build_task_queue_from_env()


class ReprocessRequest(BaseModel):
    version_id: str = Field(..., min_length=1)
    reuse_mineru_artifacts: bool | None = True
    mineru_api_base: str | None = None
    mineru_api_key: str | None = None
    llm_provider: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_base_url: str | None = None
    embedding_provider: str | None = None
    embedding_api_key: str | None = None
    embedding_model: str | None = None
    embedding_base_url: str | None = None
    rerank_provider: str | None = None
    rerank_api_key: str | None = None
    rerank_model: str | None = None
    rerank_base_url: str | None = None
    vl_provider: str | None = None
    vl_api_key: str | None = None
    vl_model: str | None = None
    vl_base_url: str | None = None


@router.get("/failed")
def list_failed(limit: int | None = Query(default=None, ge=1, le=1000)) -> dict:
    items = list_failed_versions(registry=REGISTRY, limit=limit)
    return {"items": items, "count": len(items)}


@router.post("/cleanup-failed")
def cleanup_failed(limit: int | None = Query(default=None, ge=1, le=1000)) -> dict:
    result = cleanup_failed_versions(registry=REGISTRY, limit=limit)
    return result


@router.post("/retry-failed")
def retry_failed(limit: int | None = Query(default=None, ge=1, le=1000)) -> dict:
    result = retry_failed_versions(registry=REGISTRY, task_queue=TASK_QUEUE, limit=limit)
    return result


@router.post("/reprocess")
def reprocess(req: ReprocessRequest) -> dict:
    runtime_config = {
        "mineru_api_base": (req.mineru_api_base or "").strip(),
        "mineru_api_key": (req.mineru_api_key or "").strip(),
        "llm_provider": (req.llm_provider or "").strip().lower(),
        "llm_api_key": (req.llm_api_key or "").strip(),
        "llm_model": (req.llm_model or "").strip(),
        "llm_base_url": (req.llm_base_url or "").strip(),
        "embedding_provider": (req.embedding_provider or "").strip().lower(),
        "embedding_api_key": (req.embedding_api_key or "").strip(),
        "embedding_model": (req.embedding_model or "").strip(),
        "embedding_base_url": (req.embedding_base_url or "").strip(),
        "rerank_provider": (req.rerank_provider or "").strip().lower(),
        "rerank_api_key": (req.rerank_api_key or "").strip(),
        "rerank_model": (req.rerank_model or "").strip(),
        "rerank_base_url": (req.rerank_base_url or "").strip(),
        "vl_provider": (req.vl_provider or "").strip().lower(),
        "vl_api_key": (req.vl_api_key or "").strip(),
        "vl_model": (req.vl_model or "").strip(),
        "vl_base_url": (req.vl_base_url or "").strip(),
    }
    if req.reuse_mineru_artifacts is not None:
        runtime_config["reuse_mineru_artifacts"] = bool(req.reuse_mineru_artifacts)
    runtime_config = {
        k: v
        for k, v in runtime_config.items()
        if v is not None and (bool(v) or (k == "reuse_mineru_artifacts" and isinstance(v, bool)))
    }
    result = reprocess_version(
        registry=REGISTRY,
        task_queue=TASK_QUEUE,
        version_id=req.version_id,
        runtime_config=runtime_config or None,
    )
    if not result.get("requeued"):
        reason = str(result.get("reason") or "unknown")
        if reason == "not_found":
            raise HTTPException(status_code=404, detail=f"version not found: {req.version_id}")
        raise HTTPException(status_code=400, detail=f"reprocess failed: {reason}")
    return result
