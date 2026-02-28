"""Admin evaluation APIs (MVP in-memory)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/admin/eval", tags=["admin-eval"])

RUNS: list[dict] = []
RESULTS: list[dict] = []


@router.get("/runs")
def list_runs() -> dict:
    return {"items": RUNS}


@router.get("/results")
def list_results() -> dict:
    return {"items": RESULTS}
