"""Admin document inspection APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.services.auth import ROLE_SYSTEM_ADMIN, require_roles
from app.services.artifact_repo import build_artifact_repo_from_env

router = APIRouter(
    prefix="/api/admin/docs",
    tags=["admin-docs"],
    dependencies=[Depends(require_roles([ROLE_SYSTEM_ADMIN]))],
)
ARTIFACT_REPO = build_artifact_repo_from_env()


@router.get("/{version_id}/artifacts")
def get_version_artifacts(version_id: str) -> dict:
    item = ARTIFACT_REPO.get_version_artifacts(version_id=version_id)
    if item is None:
        raise HTTPException(status_code=404, detail="version not found")
    return item
