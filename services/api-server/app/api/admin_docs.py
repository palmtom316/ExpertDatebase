"""Admin document inspection APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

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


@router.get("/{version_id}/artifacts")
def get_version_artifacts(version_id: str) -> dict:
    item = ARTIFACT_REPO.get_version_artifacts(version_id=version_id)
    if item is None:
        raise HTTPException(status_code=404, detail="version not found")
    return item


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
