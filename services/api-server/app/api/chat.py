"""Chat API routes."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.services.auth import ALL_ROLES, require_roles
from app.services.chat_orchestrator import chat_with_citations
from app.services.entity_index import build_entity_index_from_env
from app.services.search_service import create_search_repo_from_env

limiter = Limiter(key_func=get_remote_address)

router = APIRouter(
    prefix="/api",
    tags=["chat"],
    dependencies=[Depends(require_roles(ALL_ROLES))],
)
REPO = create_search_repo_from_env()
ENTITY_INDEX = build_entity_index_from_env()


@router.post("/chat")
@limiter.limit(os.getenv("RATE_LIMIT_CHAT", "30/minute"))
def chat(request: Request, payload: dict) -> dict:
    question = str(payload.get("question", "")).strip()
    mode = str(payload.get("mode") or "qa").strip().lower()
    if mode not in {"qa", "constraint"}:
        mode = "qa"
    selected_doc_id = str(payload.get("selected_doc_id") or "").strip()
    selected_version_id = str(payload.get("selected_version_id") or "").strip()
    runtime_config = {
        "llm_provider": str(payload.get("llm_provider") or "").strip().lower(),
        "llm_api_key": str(payload.get("llm_api_key") or "").strip(),
        "llm_model": str(payload.get("llm_model") or "").strip(),
        "llm_base_url": str(payload.get("llm_base_url") or "").strip(),
        "embedding_provider": str(payload.get("embedding_provider") or "").strip().lower(),
        "embedding_api_key": str(payload.get("embedding_api_key") or "").strip(),
        "embedding_model": str(payload.get("embedding_model") or "").strip(),
        "embedding_base_url": str(payload.get("embedding_base_url") or "").strip(),
        "rerank_provider": str(payload.get("rerank_provider") or "").strip().lower(),
        "rerank_api_key": str(payload.get("rerank_api_key") or "").strip(),
        "rerank_model": str(payload.get("rerank_model") or "").strip(),
        "rerank_base_url": str(payload.get("rerank_base_url") or "").strip(),
    }
    runtime_config = {k: v for k, v in runtime_config.items() if v}
    search_must: list[dict] = []
    if selected_doc_id:
        search_must.append({"key": "doc_id", "match": {"value": selected_doc_id}})
    elif selected_version_id:
        search_must.append({"key": "version_id", "match": {"value": selected_version_id}})
    search_filter = {"must": search_must} if search_must else None
    return chat_with_citations(
        question=question,
        repo=REPO,
        entity_index=ENTITY_INDEX,
        runtime_config=runtime_config,
        search_filter=search_filter,
        mode=mode,
    )
