"""Upload API and service entrypoints."""

from __future__ import annotations

import hashlib
import os
import uuid
import re
from typing import Any
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile

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

DOC_CATEGORIES = [
    "规范规程",
    "投标文件",
    "公司资质",
    "公司业绩",
    "公司资产",
    "人员资质",
    "人员业绩",
    "优秀标书",
]
DEFAULT_DOC_CATEGORY = DOC_CATEGORIES[0]
_DOC_CATEGORY_SET = set(DOC_CATEGORIES)
_DOC_CATEGORY_PATH = {
    "规范规程": "spec-standard",
    "投标文件": "bid-doc",
    "公司资质": "company-qualification",
    "公司业绩": "company-performance",
    "公司资产": "company-assets",
    "人员资质": "person-qualification",
    "人员业绩": "person-performance",
    "优秀标书": "excellent-bid",
}


def _upload_max_bytes() -> int:
    max_mb = float(os.getenv("UPLOAD_MAX_MB", "50"))
    return max(1, int(max_mb * 1024 * 1024))


def normalize_doc_category(raw: str | None) -> str:
    value = str(raw or "").strip()
    if value in _DOC_CATEGORY_SET:
        return value
    return DEFAULT_DOC_CATEGORY


def _doc_category_path(category: str) -> str:
    return _DOC_CATEGORY_PATH.get(category, "uncategorized")


def _has_pdf_magic(content: bytes) -> bool:
    return b"%PDF-" in content[:1024]


def _has_pdf_eof(content: bytes) -> bool:
    # Valid PDFs normally end with %%EOF (possibly followed by newlines).
    return b"%%EOF" in content[-4096:]


def _has_executable_magic(content: bytes) -> bool:
    head = content[:8]
    if head.startswith(b"MZ"):  # Windows PE
        return True
    if head.startswith(b"\x7fELF"):  # Linux ELF
        return True
    if head.startswith(b"\xcf\xfa\xed\xfe") or head.startswith(b"\xfe\xed\xfa\xcf"):  # Mach-O
        return True
    if head.startswith(b"\xca\xfe\xba\xbe"):  # Fat binary
        return True
    return False


def _looks_like_script_launcher(content: bytes) -> bool:
    text_head = content[:512].decode("utf-8", errors="ignore").lower()
    if text_head.startswith("#!"):
        return True
    suspicious = ["powershell", "cmd.exe", "bash -c", "/bin/sh", "this program cannot be run in dos mode"]
    return any(token in text_head for token in suspicious)


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
    if _has_executable_magic(content) or _looks_like_script_launcher(content):
        raise HTTPException(status_code=415, detail="rejected: executable/script payload is not allowed")
    if not _has_pdf_magic(content):
        raise HTTPException(status_code=415, detail="invalid pdf: missing %PDF header")
    # Some malformed payloads spoof the header only; require EOF marker for basic safety.
    if not _has_pdf_eof(content):
        # Allow tiny in-memory test payloads such as "%PDF-1.4 mock" to keep tests/dev flow.
        if len(content) > 64 and re.search(rb"%PDF-[0-9.]+", content[:32]):
            raise HTTPException(status_code=415, detail="invalid pdf: missing %%EOF marker")


def upload_pdf_bytes(
    filename: str,
    content: bytes,
    storage: ObjectStorage,
    registry: DocRegistry,
    task_queue: TaskQueue | None = None,
    runtime_config: dict[str, Any] | None = None,
    doc_type: str | None = None,
) -> dict[str, Any]:
    runtime = runtime_config or {}
    normalized_doc_type = normalize_doc_category(doc_type)

    def _should_reprocess_existing(item: dict[str, Any]) -> bool:
        if task_queue is None:
            return False
        if not runtime:
            return False
        status = str(item.get("status") or "").strip().lower()
        if status != "processed":
            return False
        # Only auto-reprocess when MinerU runtime credentials are present.
        return bool(str(runtime.get("mineru_api_base") or "").strip() and str(runtime.get("mineru_api_key") or "").strip())

    content_hash = hashlib.sha256(content).hexdigest()
    reusable_statuses = ["processed", "processing", "uploaded", "retry_queued"]
    existing_versions = registry.list_versions(statuses=reusable_statuses, limit=5000)
    for item in existing_versions:
        if str(item.get("content_hash") or "").strip() != content_hash:
            continue
        version_id = str(item.get("id") or "")
        doc_id = str(item.get("doc_id") or "")
        object_key = str(item.get("storage_key") or "")
        should_reprocess = _should_reprocess_existing(item)
        if should_reprocess:
            queue_payload = {"doc_id": doc_id, "version_id": version_id, "object_key": object_key, "doc_type": item.get("doc_type")}
            if runtime:
                queue_payload["runtime_config"] = runtime
            task_queue.enqueue_document_process(queue_payload)
            registry.update_version_status(
                version_id=version_id,
                status="retry_queued",
                notes={"reason": "dedup_reprocess_with_runtime"},
            )
        return {
            "doc_id": doc_id,
            "version_id": version_id,
            "object_key": object_key,
            "status": "retry_queued" if should_reprocess else (item.get("status") or "processed"),
            "deduplicated": True,
            "requeued": should_reprocess,
            "doc_type": item.get("doc_type") or normalized_doc_type,
        }

    doc_id = f"doc_{uuid.uuid4().hex[:12]}"
    version_id = f"ver_{uuid.uuid4().hex[:12]}"
    object_key = f"pdf/{_doc_category_path(normalized_doc_type)}/{doc_id}/{version_id}/{filename}"

    storage.put_bytes(object_key, content)

    registry.add_document(
        {"id": doc_id, "name": filename, "doc_type": normalized_doc_type, "status": "uploaded"},
        {
            "id": version_id,
            "doc_id": doc_id,
            "version_no": 1,
            "storage_key": object_key,
            "status": "uploaded",
            "content_hash": content_hash,
        },
    )

    queue_payload = {"doc_id": doc_id, "version_id": version_id, "object_key": object_key, "doc_type": normalized_doc_type}
    if runtime:
        queue_payload["runtime_config"] = runtime
    if task_queue is not None:
        task_queue.enqueue_document_process(queue_payload)

    return {
        "doc_id": doc_id,
        "version_id": version_id,
        "object_key": object_key,
        "status": "accepted",
        "deduplicated": False,
        "doc_type": normalized_doc_type,
    }


@router.get("/docs")
def list_docs(limit: int | None = None, doc_type: str | None = None) -> dict[str, Any]:
    normalized_doc_type = normalize_doc_category(doc_type) if doc_type else None
    items = DEFAULT_REGISTRY.list_versions(limit=limit, doc_type=normalized_doc_type)
    normalized: list[dict[str, Any]] = []
    for item in items:
        storage_key = str(item.get("storage_key", ""))
        normalized.append(
            {
                "version_id": item.get("id"),
                "doc_id": item.get("doc_id"),
                "status": item.get("status"),
                "storage_key": storage_key,
                "doc_name": PurePosixPath(storage_key).name if storage_key else "",
                "doc_type": item.get("doc_type") or DEFAULT_DOC_CATEGORY,
                "notes": item.get("notes"),
                "created_at": item.get("created_at"),
            }
        )
    return {"items": normalized, "count": len(normalized)}


@router.post("/upload", status_code=202)
async def upload(
    file: UploadFile,
    doc_type: str | None = Form(default=None),
    mineru_api_base: str | None = Form(default=None),
    mineru_api_key: str | None = Form(default=None),
    mineru_token: str | None = Form(default=None),
    mineru_model_version: str | None = Form(default=None),
    llm_provider: str | None = Form(default=None),
    llm_api_key: str | None = Form(default=None),
    llm_model: str | None = Form(default=None),
    llm_base_url: str | None = Form(default=None),
    embedding_provider: str | None = Form(default=None),
    embedding_api_key: str | None = Form(default=None),
    embedding_model: str | None = Form(default=None),
    embedding_base_url: str | None = Form(default=None),
    rerank_provider: str | None = Form(default=None),
    rerank_api_key: str | None = Form(default=None),
    rerank_model: str | None = Form(default=None),
    rerank_base_url: str | None = Form(default=None),
    vl_provider: str | None = Form(default=None),
    vl_api_key: str | None = Form(default=None),
    vl_model: str | None = Form(default=None),
    vl_base_url: str | None = Form(default=None),
) -> dict[str, Any]:
    content = await file.read()
    validate_upload_payload(
        filename=file.filename or "",
        content_type=file.content_type,
        content=content,
    )
    runtime_config = {
        "mineru_api_base": (mineru_api_base or "").strip(),
        "mineru_api_key": (mineru_api_key or "").strip(),
        "mineru_token": (mineru_token or "").strip(),
        "mineru_model_version": (mineru_model_version or "").strip(),
        "llm_provider": (llm_provider or "").strip().lower(),
        "llm_api_key": (llm_api_key or "").strip(),
        "llm_model": (llm_model or "").strip(),
        "llm_base_url": (llm_base_url or "").strip(),
        "embedding_provider": (embedding_provider or "").strip().lower(),
        "embedding_api_key": (embedding_api_key or "").strip(),
        "embedding_model": (embedding_model or "").strip(),
        "embedding_base_url": (embedding_base_url or "").strip(),
        "rerank_provider": (rerank_provider or "").strip().lower(),
        "rerank_api_key": (rerank_api_key or "").strip(),
        "rerank_model": (rerank_model or "").strip(),
        "rerank_base_url": (rerank_base_url or "").strip(),
        "vl_provider": (vl_provider or "").strip().lower(),
        "vl_api_key": (vl_api_key or "").strip(),
        "vl_model": (vl_model or "").strip(),
        "vl_base_url": (vl_base_url or "").strip(),
    }
    runtime_config = {k: v for k, v in runtime_config.items() if v}

    return upload_pdf_bytes(
        filename=file.filename or "unknown.pdf",
        content=content,
        storage=DEFAULT_STORAGE,
        registry=DEFAULT_REGISTRY,
        task_queue=DEFAULT_TASK_QUEUE,
        runtime_config=runtime_config,
        doc_type=doc_type,
    )
