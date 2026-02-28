"""Hybrid search service."""

from __future__ import annotations

from typing import Any

from app.services.filter_parser import parse_filter_spec


class InMemoryQdrantRepo:
    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []

    def upsert(self, point_id: str, vector: list[float], payload: dict[str, Any]) -> None:
        self._records = [r for r in self._records if r["id"] != point_id]
        self._records.append({"id": point_id, "vector": vector, "payload": payload})

    def search(self, query_vector: list[float], filter_json: dict[str, Any] | None, limit: int = 5) -> list[dict[str, Any]]:
        result = [r for r in self._records if _match_filter(r["payload"], filter_json)]
        return result[:limit]


class SimpleEmbeddingClient:
    def embed_text(self, text: str) -> list[float]:
        n = max(len(text), 1)
        return [0.1, min(n / 1000.0, 1.0)]


def _match_filter(payload: dict[str, Any], filter_json: dict[str, Any] | None) -> bool:
    if not filter_json:
        return True

    for cond in filter_json.get("must", []):
        key = cond["key"]
        value = payload.get(key)
        if "match" in cond:
            any_values = cond["match"].get("any")
            target = cond["match"].get("value")
            values = value if isinstance(value, list) else [value]
            if any_values is not None and not any(v in values for v in any_values):
                return False
            if target is not None and target not in values:
                return False
        if "range" in cond:
            if value is None:
                return False
            gte = cond["range"].get("gte")
            if gte is not None and value < gte:
                return False
    return True


def _to_citation(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "doc_name": payload.get("doc_name", ""),
        "page_start": payload.get("page_start"),
        "page_end": payload.get("page_end"),
        "excerpt": payload.get("excerpt", ""),
    }


def hybrid_search(
    question: str,
    repo: InMemoryQdrantRepo,
    entity_index: Any,
    top_k: int = 5,
) -> dict[str, Any]:
    filter_json, vector_query_text = parse_filter_spec(question, entity_index)
    query_vector = SimpleEmbeddingClient().embed_text(vector_query_text)
    hits = repo.search(query_vector=query_vector, filter_json=filter_json, limit=top_k)

    citations = [_to_citation(h["payload"]) for h in hits]
    return {
        "hits": hits,
        "citations": citations,
        "filter_json": filter_json,
    }
