"""Qdrant repository adapters for worker-side indexing/search."""

from __future__ import annotations

import os
from typing import Any, Protocol

import requests


class QdrantRepo(Protocol):
    def upsert(self, point_id: str, vector: list[float], payload: dict[str, Any]) -> None:
        raise NotImplementedError

    def search(self, query_vector: list[float], filter_json: dict[str, Any] | None, limit: int = 5) -> list[dict[str, Any]]:
        raise NotImplementedError


class InMemoryQdrantRepo:
    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []

    def upsert(self, point_id: str, vector: list[float], payload: dict[str, Any]) -> None:
        self._records = [r for r in self._records if r["id"] != point_id]
        self._records.append({"id": point_id, "vector": vector, "payload": payload})

    def search(self, query_vector: list[float], filter_json: dict[str, Any] | None, limit: int = 5) -> list[dict[str, Any]]:
        results = [r for r in self._records if _match_filter(r["payload"], filter_json)]
        return results[:limit]


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

    def _url(self, suffix: str) -> str:
        return f"{self.endpoint}{suffix}"

    def upsert(self, point_id: str, vector: list[float], payload: dict[str, Any]) -> None:
        body = {
            "points": [
                {
                    "id": point_id,
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

        return [
            {"id": item.get("id"), "score": item.get("score"), "payload": item.get("payload", {})}
            for item in result
        ]


def create_qdrant_repo_from_env() -> QdrantRepo:
    backend = os.getenv("VECTORDB_BACKEND", "auto").lower()
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


def _match_filter(payload: dict[str, Any], filter_json: dict[str, Any] | None) -> bool:
    if not filter_json:
        return True
    for cond in filter_json.get("must", []):
        key = cond["key"]
        if "match" in cond:
            target_any = cond["match"].get("any")
            target_value = cond["match"].get("value")
            pv = payload.get(key)
            if target_any is not None:
                pv_list = pv if isinstance(pv, list) else [pv]
                if not any(v in pv_list for v in target_any):
                    return False
            elif target_value is not None:
                if pv != target_value:
                    return False
        if "range" in cond:
            pv = payload.get(key)
            if pv is None:
                return False
            gte = cond["range"].get("gte")
            lte = cond["range"].get("lte")
            if gte is not None and pv < gte:
                return False
            if lte is not None and pv > lte:
                return False
    return True
