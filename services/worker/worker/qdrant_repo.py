"""Qdrant repository adapters for worker-side indexing/search."""

from __future__ import annotations

import os
import time
from typing import Any, Protocol
from uuid import UUID, uuid5, NAMESPACE_URL

import requests


class QdrantRepo(Protocol):
    def upsert(self, point_id: str, vector: list[float], payload: dict[str, Any]) -> None:
        raise NotImplementedError

    def search(self, query_vector: list[float], filter_json: dict[str, Any] | None, limit: int = 5) -> list[dict[str, Any]]:
        raise NotImplementedError

    def delete_by_version(self, version_id: str) -> None:
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

    def delete_by_version(self, version_id: str) -> None:
        target = str(version_id or "").strip()
        if not target:
            return
        self._records = [r for r in self._records if str((r.get("payload") or {}).get("version_id") or "") != target]


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
        self.upsert_max_retries = max(0, int(os.getenv("QDRANT_UPSERT_MAX_RETRIES", "2")))
        self.upsert_retry_delay_s = max(0.0, float(os.getenv("QDRANT_UPSERT_RETRY_DELAY_S", "0.4")))
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
        # 200/201 => created/updated, 409 => already exists
        if resp.status_code not in (200, 201, 409):
            resp.raise_for_status()
        self._collection_ready = True

    def _recreate_collection(self, vector_size: int) -> None:
        # Recovery path for deleted/mismatched collections.
        requests.delete(
            self._url(f"/collections/{self.collection}"),
            timeout=self.timeout_s,
        )
        self._collection_ready = False
        self._ensure_collection(vector_size)

    def _error_text(self, resp: requests.Response | None) -> str:
        if resp is None:
            return ""
        try:
            return str(getattr(resp, "text", "") or "")
        except Exception:  # noqa: BLE001
            return ""

    def _is_recoverable_upsert_error(self, status_code: int, body: str) -> bool:
        text = (body or "").lower()
        if status_code == 404:
            return True
        allow_dim_recreate = str(os.getenv("QDRANT_ALLOW_RECREATE_ON_DIM_MISMATCH", "0")).strip().lower() in {"1", "true", "yes", "on"}
        if allow_dim_recreate and status_code == 400 and any(k in text for k in ["dimension", "vector", "wrong", "size", "not match"]):
            return True
        return False

    def _normalize_point_id(self, point_id: str) -> str:
        try:
            UUID(str(point_id))
            return str(point_id)
        except ValueError:
            return str(uuid5(NAMESPACE_URL, str(point_id)))

    def _put_with_retry(self, endpoint: str, body: dict[str, Any]) -> requests.Response:
        last_exc: Exception | None = None
        for attempt in range(self.upsert_max_retries + 1):
            try:
                return requests.put(endpoint, json=body, timeout=self.timeout_s)
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_exc = exc
                if attempt >= self.upsert_max_retries:
                    break
                if self.upsert_retry_delay_s > 0:
                    time.sleep(self.upsert_retry_delay_s)
        if last_exc is not None:
            raise RuntimeError(f"qdrant upsert timeout after retries: {last_exc}") from last_exc
        raise RuntimeError("qdrant upsert failed without explicit exception")

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
        endpoint = self._url(f"/collections/{self.collection}/points?wait=true")
        resp = self._put_with_retry(endpoint=endpoint, body=body)
        try:
            resp.raise_for_status()
            return
        except requests.HTTPError as exc:
            status_code = int(getattr(resp, "status_code", 0) or 0)
            body_text = self._error_text(resp)
            if self._is_recoverable_upsert_error(status_code=status_code, body=body_text):
                self._recreate_collection(len(vector))
                retry_resp = self._put_with_retry(endpoint=endpoint, body=body)
                try:
                    retry_resp.raise_for_status()
                    return
                except requests.HTTPError as retry_exc:
                    retry_body = self._error_text(retry_resp)
                    raise RuntimeError(f"{retry_exc} | body={retry_body[:300]}") from retry_exc
            raise RuntimeError(f"{exc} | body={body_text[:300]}") from exc

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

    def delete_by_version(self, version_id: str) -> None:
        target = str(version_id or "").strip()
        if not target:
            return
        body = {
            "filter": {
                "must": [
                    {
                        "key": "version_id",
                        "match": {"value": target},
                    }
                ]
            }
        }
        resp = requests.post(
            self._url(f"/collections/{self.collection}/points/delete?wait=true"),
            json=body,
            timeout=self.timeout_s,
        )
        if resp.status_code == 404:
            # Fresh deployments may not have created the collection yet.
            # In that case there is nothing to delete and indexing can continue.
            self._collection_ready = False
            return
        resp.raise_for_status()


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
            timeout_s=float(os.getenv("QDRANT_HTTP_TIMEOUT_S", "12")),
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
