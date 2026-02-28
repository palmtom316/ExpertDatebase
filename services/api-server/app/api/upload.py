"""Upload API and service entrypoints."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, UploadFile

from app.services.doc_registry import DocRegistry, build_doc_registry_from_env
from app.services.storage import ObjectStorage, build_storage_from_env
from app.services.task_queue import TaskQueue, build_task_queue_from_env

router = APIRouter(prefix="/api", tags=["upload"])


DEFAULT_STORAGE = build_storage_from_env()
DEFAULT_REGISTRY = build_doc_registry_from_env()
DEFAULT_TASK_QUEUE = build_task_queue_from_env()


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
    return upload_pdf_bytes(
        filename=file.filename or "unknown.pdf",
        content=content,
        storage=DEFAULT_STORAGE,
        registry=DEFAULT_REGISTRY,
        task_queue=DEFAULT_TASK_QUEUE,
    )
