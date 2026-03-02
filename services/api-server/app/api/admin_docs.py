"""Admin document inspection APIs."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from app.services.auth import ROLE_SYSTEM_ADMIN, require_roles
from app.services.artifact_repo import build_artifact_repo_from_env
from app.services.doc_registry import build_doc_registry_from_env
from app.services.search_service import create_search_repo_from_env
from app.services.storage import build_storage_from_env

router = APIRouter(
    prefix="/api/admin/docs",
    tags=["admin-docs"],
    dependencies=[Depends(require_roles([ROLE_SYSTEM_ADMIN]))],
)
ARTIFACT_REPO = build_artifact_repo_from_env()
DOC_REGISTRY = build_doc_registry_from_env()
OBJECT_STORAGE = build_storage_from_env()
SEARCH_REPO = create_search_repo_from_env()
RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


@router.get("/{version_id}/artifacts")
def get_version_artifacts(version_id: str) -> dict:
    item = ARTIFACT_REPO.get_version_artifacts(version_id=version_id)
    if item is None:
        raise HTTPException(status_code=404, detail="version not found")
    return item


def _resolve_source_pdf(version_id: str) -> tuple[str, str, int]:
    item = ARTIFACT_REPO.get_version_artifacts(version_id=version_id)
    if item is None:
        raise HTTPException(status_code=404, detail="version not found")
    version = item.get("version") if isinstance(item, dict) else {}
    storage_key = str((version or {}).get("storage_key") or "").strip()
    if not storage_key:
        raise HTTPException(status_code=404, detail="source pdf not found")
    filename = storage_key.rsplit("/", 1)[-1] or "source.pdf"
    try:
        size = int(OBJECT_STORAGE.get_size(storage_key))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=f"source pdf unavailable: {exc}") from exc
    if size <= 0:
        raise HTTPException(status_code=404, detail="source pdf unavailable: empty file")
    return storage_key, filename, size


def _base_pdf_headers(filename: str) -> dict[str, str]:
    safe_filename = quote(filename, safe="")
    return {
        "Content-Disposition": f"inline; filename*=UTF-8''{safe_filename}",
        "Cache-Control": "no-store",
        "Accept-Ranges": "bytes",
    }


def _parse_single_range(range_header: str, size: int) -> tuple[int, int]:
    text = str(range_header or "").strip()
    if not text:
        raise HTTPException(status_code=416, detail="invalid range")
    if "," in text:
        raise HTTPException(status_code=416, detail="multiple ranges not supported")
    match = RANGE_RE.match(text)
    if not match:
        raise HTTPException(status_code=416, detail="invalid range")
    start_raw, end_raw = match.groups()
    if not start_raw and not end_raw:
        raise HTTPException(status_code=416, detail="invalid range")

    if start_raw:
        try:
            start = int(start_raw)
        except ValueError as exc:
            raise HTTPException(status_code=416, detail="invalid range") from exc
        if start >= size:
            raise HTTPException(status_code=416, detail="range not satisfiable")
        if end_raw:
            try:
                end = int(end_raw)
            except ValueError as exc:
                raise HTTPException(status_code=416, detail="invalid range") from exc
        else:
            end = size - 1
        if end < start:
            raise HTTPException(status_code=416, detail="range not satisfiable")
        end = min(end, size - 1)
        return start, end

    try:
        suffix = int(end_raw)
    except ValueError as exc:
        raise HTTPException(status_code=416, detail="invalid range") from exc
    if suffix <= 0:
        raise HTTPException(status_code=416, detail="range not satisfiable")
    if suffix >= size:
        return 0, size - 1
    return size - suffix, size - 1


@router.head("/{version_id}/source-pdf")
def head_source_pdf(version_id: str) -> Response:
    _, filename, size = _resolve_source_pdf(version_id=version_id)
    headers = _base_pdf_headers(filename)
    headers["Content-Length"] = str(size)
    return Response(status_code=200, media_type="application/pdf", headers=headers)


@router.get("/{version_id}/source-pdf")
def get_source_pdf(version_id: str, request: Request) -> Response:
    storage_key, filename, size = _resolve_source_pdf(version_id=version_id)
    headers = _base_pdf_headers(filename)
    range_header = str(request.headers.get("range") or "").strip()

    if not range_header:
        try:
            payload = OBJECT_STORAGE.get_bytes(storage_key)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=404, detail=f"source pdf unavailable: {exc}") from exc
        headers["Content-Length"] = str(len(payload))
        return Response(content=payload, media_type="application/pdf", headers=headers)

    try:
        start, end = _parse_single_range(range_header=range_header, size=size)
    except HTTPException as exc:
        if exc.status_code == 416:
            err_headers = _base_pdf_headers(filename)
            err_headers["Content-Range"] = f"bytes */{size}"
            return Response(status_code=416, headers=err_headers)
        raise

    try:
        payload = OBJECT_STORAGE.get_range(storage_key, start=start, end=end)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=f"source pdf unavailable: {exc}") from exc

    actual_end = start + max(0, len(payload) - 1)
    headers["Content-Range"] = f"bytes {start}-{actual_end}/{size}"
    headers["Content-Length"] = str(len(payload))
    return Response(
        content=payload,
        status_code=206,
        media_type="application/pdf",
        headers=headers,
    )


def _storage_keys_from_item(item: dict[str, Any]) -> list[str]:
    version = (item or {}).get("version") or {}
    notes = version.get("notes") if isinstance(version.get("notes"), dict) else {}
    keys = [
        version.get("storage_key"),
        notes.get("mineru_json_key"),
        notes.get("mineru_md_key"),
        version.get("mineru_json_key"),
        version.get("mineru_md_key"),
    ]
    out: list[str] = []
    for key in keys:
        text = str(key or "").strip()
        if text and text not in out:
            out.append(text)
    return out


@router.delete("/{version_id}")
def delete_version(version_id: str) -> dict:
    item = ARTIFACT_REPO.get_version_artifacts(version_id=version_id)
    if item is None:
        raise HTTPException(status_code=404, detail="version not found")

    keys = _storage_keys_from_item(item)
    object_deleted: list[str] = []
    object_delete_errors: list[str] = []
    for key in keys:
        try:
            OBJECT_STORAGE.delete_bytes(key)
            object_deleted.append(key)
        except Exception as exc:  # noqa: BLE001
            object_delete_errors.append(f"{key}: {exc}")

    assets_deleted = ARTIFACT_REPO.delete_version_assets(version_id=version_id)
    deleted = DOC_REGISTRY.delete_version(version_id=version_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail="version not found")

    vector_delete_error = ""
    try:
        SEARCH_REPO.delete_by_version(version_id=version_id)
    except Exception as exc:  # noqa: BLE001
        vector_delete_error = str(exc)

    return {
        "ok": True,
        "version_id": version_id,
        "doc_id": deleted.get("doc_id"),
        "deleted_assets": assets_deleted,
        "deleted_objects": object_deleted,
        "object_delete_errors": object_delete_errors,
        "vector_cleanup_error": vector_delete_error,
    }
