"""Hybrid search service with in-memory and Qdrant HTTP backends."""

from __future__ import annotations

import os
from typing import Any, Protocol
from uuid import UUID, uuid5, NAMESPACE_URL

import requests

from app.services.filter_parser import parse_filter_spec


class SearchRepo(Protocol):
    def search(self, query_vector: list[float], filter_json: dict[str, Any] | None, limit: int = 5) -> list[dict[str, Any]]:
        raise NotImplementedError


class InMemoryQdrantRepo:
    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []

    def upsert(self, point_id: str, vector: list[float], payload: dict[str, Any]) -> None:
        self._records = [r for r in self._records if r["id"] != point_id]
        self._records.append({"id": point_id, "vector": vector, "payload": payload})

    def search(self, query_vector: list[float], filter_json: dict[str, Any] | None, limit: int = 5) -> list[dict[str, Any]]:
        result = [r for r in self._records if _match_filter(r["payload"], filter_json)]
        return result[:limit]


class QdrantHttpRepo:
    def __init__(
        self,
        endpoint: str,
        collection: str = "chunks_v1",
        vector_name: str = "text_embedding",
        timeout_s: float = 8.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.collection = collection
        self.vector_name = vector_name
        self.timeout_s = timeout_s
        self._collection_ready = False

    def _url(self, suffix: str) -> str:
        return f"{self.endpoint}{suffix}"

    def _ensure_collection(self, vector_size: int) -> None:
        if self._collection_ready:
            return
        body = {
            "vectors": {
                self.vector_name: {
                    "size": int(vector_size),
                    "distance": "Cosine",
                }
            }
        }
        resp = requests.put(
            self._url(f"/collections/{self.collection}"),
            json=body,
            timeout=self.timeout_s,
        )
        if resp.status_code not in (200, 201, 409):
            resp.raise_for_status()
        self._collection_ready = True

    def _normalize_point_id(self, point_id: str) -> str:
        try:
            UUID(str(point_id))
            return str(point_id)
        except ValueError:
            return str(uuid5(NAMESPACE_URL, str(point_id)))

    def upsert(self, point_id: str, vector: list[float], payload: dict[str, Any]) -> None:
        self._ensure_collection(len(vector))
        body = {
            "points": [
                {
                    "id": self._normalize_point_id(point_id),
                    "vector": {self.vector_name: vector},
                    "payload": payload,
                }
            ]
        }
        resp = requests.put(
            self._url(f"/collections/{self.collection}/points?wait=true"),
            json=body,
            timeout=self.timeout_s,
        )
        resp.raise_for_status()

    def search(self, query_vector: list[float], filter_json: dict[str, Any] | None, limit: int = 5) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "vector": {"name": self.vector_name, "vector": query_vector},
            "limit": limit,
        }
        if filter_json:
            body["filter"] = filter_json

        resp = requests.post(
            self._url(f"/collections/{self.collection}/points/search"),
            json=body,
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        result = resp.json().get("result", [])

        hits: list[dict[str, Any]] = []
        for item in result:
            hits.append(
                {
                    "id": item.get("id"),
                    "score": item.get("score"),
                    "payload": item.get("payload", {}),
                }
            )
        return hits


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


def create_search_repo_from_env() -> SearchRepo:
    backend = os.getenv("SEARCH_REPO_BACKEND", "auto").lower()
    if backend == "memory":
        return InMemoryQdrantRepo()

    endpoint = os.getenv("VECTORDB_ENDPOINT")
    if endpoint:
        if not endpoint.startswith("http"):
            endpoint = f"http://{endpoint}"
        return QdrantHttpRepo(
            endpoint=endpoint,
            collection=os.getenv("QDRANT_COLLECTION", "chunks_v1"),
            vector_name=os.getenv("QDRANT_VECTOR_NAME", "text_embedding"),
        )

    return InMemoryQdrantRepo()


def hybrid_search(
    question: str,
    repo: SearchRepo,
    entity_index: Any,
    top_k: int = 5,
) -> dict[str, Any]:
    filter_json, vector_query_text = parse_filter_spec(question, entity_index)
    query_vector = SimpleEmbeddingClient().embed_text(vector_query_text)
    hits = repo.search(query_vector=query_vector, filter_json=filter_json, limit=top_k)

    citations = [_to_citation((h or {}).get("payload", {})) for h in hits]
    return {
        "hits": hits,
        "citations": citations,
        "filter_json": filter_json,
    }
