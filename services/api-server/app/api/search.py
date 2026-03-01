"""Search API routes."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Query, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.services.auth import ALL_ROLES, require_roles
from app.services.entity_index import build_entity_index_from_env
from app.services.search_service import create_search_repo_from_env, hybrid_search

limiter = Limiter(key_func=get_remote_address)

router = APIRouter(
    prefix="/api",
    tags=["search"],
    dependencies=[Depends(require_roles(ALL_ROLES))],
)
REPO = create_search_repo_from_env()
ENTITY_INDEX = build_entity_index_from_env()


@router.get("/search")
@limiter.limit(os.getenv("RATE_LIMIT_SEARCH", "60/minute"))
def search(request: Request, q: str = Query(default="", description="user question")) -> dict:
    if not q.strip():
        return {"hits": [], "citations": [], "filter_json": None}
    return hybrid_search(question=q, repo=REPO, entity_index=ENTITY_INDEX, top_k=5)
