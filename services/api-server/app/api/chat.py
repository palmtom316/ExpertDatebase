"""Chat API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.services.auth import ALL_ROLES, require_roles
from app.services.chat_orchestrator import chat_with_citations
from app.services.search_service import create_search_repo_from_env

router = APIRouter(
    prefix="/api",
    tags=["chat"],
    dependencies=[Depends(require_roles(ALL_ROLES))],
)
REPO = create_search_repo_from_env()


class _EmptyEntityIndex:
    def match_names(self, kind: str, question: str) -> list[str]:
        return []

    def get_id(self, kind: str, name: str) -> str | None:
        return None


@router.post("/chat")
def chat(payload: dict) -> dict:
    question = str(payload.get("question", "")).strip()
    runtime_config = {
        "llm_provider": str(payload.get("llm_provider") or "").strip().lower(),
        "llm_api_key": str(payload.get("llm_api_key") or "").strip(),
        "llm_model": str(payload.get("llm_model") or "").strip(),
        "llm_base_url": str(payload.get("llm_base_url") or "").strip(),
    }
    runtime_config = {k: v for k, v in runtime_config.items() if v}
    return chat_with_citations(
        question=question,
        repo=REPO,
        entity_index=_EmptyEntityIndex(),
        runtime_config=runtime_config,
    )
