"""Admin evaluation APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.services.auth import ROLE_SYSTEM_ADMIN, require_roles
from app.services.eval_repo import build_eval_repo_from_env

router = APIRouter(
    prefix="/api/admin/eval",
    tags=["admin-eval"],
    dependencies=[Depends(require_roles([ROLE_SYSTEM_ADMIN]))],
)
EVAL_REPO = build_eval_repo_from_env()

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
