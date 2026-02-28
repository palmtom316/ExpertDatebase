"""Upload API and service entrypoints."""

from __future__ import annotations

import os
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from app.services.auth import ALL_ROLES, require_roles
from app.services.doc_registry import DocRegistry, build_doc_registry_from_env
from app.services.storage import ObjectStorage, build_storage_from_env
from app.services.task_queue import TaskQueue, build_task_queue_from_env

router = APIRouter(
    prefix="/api",
    tags=["upload"],
    dependencies=[Depends(require_roles(ALL_ROLES))],
)


DEFAULT_STORAGE = build_storage_from_env()
DEFAULT_REGISTRY = build_doc_registry_from_env()
DEFAULT_TASK_QUEUE = build_task_queue_from_env()


def _upload_max_bytes() -> int:
    max_mb = float(os.getenv("UPLOAD_MAX_MB", "50"))
    return max(1, int(max_mb * 1024 * 1024))


def validate_upload_payload(filename: str, content_type: str | None, content: bytes) -> None:
    lower_name = (filename or "").strip().lower()
    ctype = (content_type or "").strip().lower()

    is_pdf_name = lower_name.endswith(".pdf")
    is_pdf_type = ctype in {"application/pdf", "application/x-pdf"}
    if not is_pdf_name and not is_pdf_type:
        raise HTTPException(status_code=415, detail="only PDF uploads are supported")

    size = len(content)
    if size <= 0:
        raise HTTPException(status_code=400, detail="empty file")
    if size > _upload_max_bytes():
        raise HTTPException(status_code=413, detail="file too large")


def upload_pdf_bytes(
    filename: str,
    content: bytes,
    storage: ObjectStorage,
    registry: DocRegistry,
    task_queue: TaskQueue | None = None,
) -> dict[str, Any]:
    doc_id = f"doc_{uuid.uuid4().hex[:12]}"
    version_id = f"ver_{uuid.uuid4().hex[:12]}"
    object_key = f"pdf/{doc_id}/{version_id}/{filename}"

    storage.put_bytes(object_key, content)

    registry.add_document(
        {"id": doc_id, "name": filename, "doc_type": "unknown", "status": "uploaded"},
        {
            "id": version_id,
            "doc_id": doc_id,
            "version_no": 1,
            "storage_key": object_key,
            "status": "uploaded",
        },
    )

    queue_payload = {"doc_id": doc_id, "version_id": version_id, "object_key": object_key}
    if task_queue is not None:
        task_queue.enqueue_document_process(queue_payload)

    return {
        "doc_id": doc_id,
        "version_id": version_id,
        "object_key": object_key,
        "status": "accepted",
    }


@router.post("/upload", status_code=202)
async def upload(file: UploadFile) -> dict[str, Any]:
    content = await file.read()
    validate_upload_payload(
        filename=file.filename or "",
        content_type=file.content_type,
        content=content,
    )
    return upload_pdf_bytes(
        filename=file.filename or "unknown.pdf",
        content=content,
        storage=DEFAULT_STORAGE,
        registry=DEFAULT_REGISTRY,
        task_queue=DEFAULT_TASK_QUEUE,
    )
