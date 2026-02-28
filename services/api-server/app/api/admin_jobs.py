"""Admin job control APIs: cleanup failed and retry failed."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.services.doc_registry import build_doc_registry_from_env
from app.services.retry_service import cleanup_failed_versions, list_failed_versions, retry_failed_versions
from app.services.task_queue import build_task_queue_from_env

router = APIRouter(prefix="/api/admin/jobs", tags=["admin-jobs"])

REGISTRY = build_doc_registry_from_env()
TASK_QUEUE = build_task_queue_from_env()


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
