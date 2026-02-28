"""Chat API routes."""

from __future__ import annotations

from fastapi import APIRouter

from app.services.chat_orchestrator import chat_with_citations
from app.services.search_service import InMemoryQdrantRepo

router = APIRouter(prefix="/api", tags=["chat"])
REPO = InMemoryQdrantRepo()


class _EmptyEntityIndex:
    def match_names(self, kind: str, question: str) -> list[str]:
        return []

    def get_id(self, kind: str, name: str) -> str | None:
        return None


@router.post("/chat")
def chat(payload: dict) -> dict:
    question = str(payload.get("question", "")).strip()
    return chat_with_citations(question=question, repo=REPO, entity_index=_EmptyEntityIndex())
