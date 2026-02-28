"""Search API routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.services.search_service import create_search_repo_from_env, hybrid_search

router = APIRouter(prefix="/api", tags=["search"])
REPO = create_search_repo_from_env()


class _EmptyEntityIndex:
    def match_names(self, kind: str, question: str) -> list[str]:
        return []

    def get_id(self, kind: str, name: str) -> str | None:
        return None


@router.get("/search")
def search(q: str = Query(default="", description="user question")) -> dict:
    if not q.strip():
        return {"hits": [], "citations": [], "filter_json": None}
    return hybrid_search(question=q, repo=REPO, entity_index=_EmptyEntityIndex(), top_k=5)
