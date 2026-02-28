"""Upload API and service entrypoints."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, UploadFile

from app.services.doc_registry import JSONDocRegistry
from app.services.storage import LocalObjectStorage

router = APIRouter(prefix="/api", tags=["upload"])


DEFAULT_STORAGE = LocalObjectStorage(Path(".runtime/objects"))
DEFAULT_REGISTRY = JSONDocRegistry(Path(".runtime/registry.json"))


def upload_pdf_bytes(
    filename: str,
    content: bytes,
    storage: LocalObjectStorage,
    registry: JSONDocRegistry,
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

    return {
        "doc_id": doc_id,
        "version_id": version_id,
        "object_key": object_key,
        "status": "accepted",
    }


@router.post("/upload", status_code=202)
async def upload(file: UploadFile) -> dict[str, Any]:
    content = await file.read()
    return upload_pdf_bytes(file.filename or "unknown.pdf", content, DEFAULT_STORAGE, DEFAULT_REGISTRY)
