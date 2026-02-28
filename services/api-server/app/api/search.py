"""Search API routes."""

from __future__ import annotations

from fastapi import APIRouter

from app.services.search_service import InMemoryQdrantRepo

router = APIRouter(prefix="/api", tags=["search"])

# Process-local repository for MVP.
REPO = InMemoryQdrantRepo()


@router.get("/search")
def search() -> dict[str, str]:
    return {"status": "ready"}
