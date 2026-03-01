"""Hybrid search service with in-memory and Qdrant HTTP backends."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from typing import Any, Protocol
from uuid import UUID, uuid5, NAMESPACE_URL

import requests

from app.services.filter_parser import parse_filter_spec


class SearchRepo(Protocol):
    def search(self, query_vector: list[float], filter_json: dict[str, Any] | None, limit: int = 5) -> list[dict[str, Any]]:
        raise NotImplementedError

    def keyword_search(self, query_text: str, filter_json: dict[str, Any] | None, limit: int = 20) -> list[dict[str, Any]]:
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
        result = [r for r in self._records if _match_filter(r["payload"], filter_json)]
        return result[:limit]

    def keyword_search(self, query_text: str, filter_json: dict[str, Any] | None, limit: int = 20) -> list[dict[str, Any]]:
        terms = _extract_query_terms(query_text)
        if not terms:
            return []
        scored: list[tuple[float, dict[str, Any]]] = []
        for r in self._records:
            payload = r.get("payload") or {}
            if not _match_filter(payload, filter_json):
                continue
            text = _payload_search_text(payload)
            score = _keyword_score(text, terms)
            if score <= 0:
                continue
            scored.append((score, {"id": r.get("id"), "score": score, "payload": payload}))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def delete_by_version(self, version_id: str) -> None:
        self._records = [r for r in self._records if str((r.get("payload") or {}).get("version_id") or "") != version_id]


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

    def _is_vector_mismatch_error(self, status_code: int, body: str) -> bool:
        text = str(body or "").lower()
        if status_code != 400:
            return False
        return any(k in text for k in ["vector", "dimension", "size", "wrong", "not match"])

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
            "query": query_vector,
            "using": self.vector_name,
            "limit": limit,
            "with_payload": True,
        }
        if filter_json:
            body["filter"] = filter_json

        resp = requests.post(
            self._url(f"/collections/{self.collection}/points/query"),
            json=body,
            timeout=self.timeout_s,
        )
        try:
            resp.raise_for_status()
        except requests.HTTPError:
            # Fresh/local environments may not have indexed data yet, and Qdrant
            # reports missing collection as 404. Treat it as empty search hits.
            if resp.status_code == 404:
                return []
            # Runtime embedding model may temporarily mismatch the indexed vector
            # dimension (e.g., user switched provider/model). Degrade to no hits
            # instead of surfacing a 500 to chat.
            if self._is_vector_mismatch_error(
                status_code=int(getattr(resp, "status_code", 0) or 0),
                body=str(getattr(resp, "text", "") or ""),
            ):
                return []
            raise
        payload = resp.json().get("result", [])
        if isinstance(payload, dict):
            result = payload.get("points", [])
        else:
            result = payload

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

    def _scroll_payloads(self, filter_json: dict[str, Any] | None, limit: int = 2000) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset: Any = None
        page_size = min(256, max(64, limit))
        while len(rows) < limit:
            body: dict[str, Any] = {
                "limit": page_size,
                "with_payload": True,
                "with_vector": False,
            }
            if filter_json:
                body["filter"] = filter_json
            if offset is not None:
                body["offset"] = offset
            resp = requests.post(
                self._url(f"/collections/{self.collection}/points/scroll"),
                json=body,
                timeout=self.timeout_s,
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            result = resp.json().get("result") or {}
            points = result.get("points") or []
            rows.extend(points)
            offset = result.get("next_page_offset")
            if not offset or not points:
                break
        return rows[:limit]

    def keyword_search(self, query_text: str, filter_json: dict[str, Any] | None, limit: int = 20) -> list[dict[str, Any]]:
        terms = _extract_query_terms(query_text)
        if not terms:
            return []
        scan_limit = max(limit * 40, int(os.getenv("KEYWORD_SCAN_MAX_POINTS", "3000")))
        points = self._scroll_payloads(filter_json=filter_json, limit=scan_limit)
        scored: list[tuple[float, dict[str, Any]]] = []
        for p in points:
            payload = p.get("payload") or {}
            text = _payload_search_text(payload)
            score = _keyword_score(text, terms)
            if score <= 0:
                continue
            scored.append(
                (
                    score,
                    {
                        "id": p.get("id"),
                        "score": score,
                        "payload": payload,
                    },
                )
            )
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def delete_by_version(self, version_id: str) -> None:
        if not version_id:
            return
        body = {"filter": {"must": [{"key": "version_id", "match": {"value": version_id}}]}}
        resp = requests.post(
            self._url(f"/collections/{self.collection}/points/delete?wait=true"),
            json=body,
            timeout=self.timeout_s,
        )
        if resp.status_code == 404:
            return
        resp.raise_for_status()


class SimpleEmbeddingClient:
    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim
        self.timeout_s = float(os.getenv("EMBEDDING_HTTP_TIMEOUT_S", "15"))

    def _normalize_token(self, raw: str) -> str:
        token = str(raw or "").strip()
        if token.lower().startswith("bearer "):
            token = token.split(" ", 1)[1].strip()
        return token

    def _resolve_runtime(self, runtime_config: dict[str, Any] | None = None) -> dict[str, str]:
        runtime = runtime_config or {}
        api_key = self._normalize_token(str(runtime.get("embedding_api_key") or ""))
        return {
            "provider": str(runtime.get("embedding_provider") or os.getenv("EMBEDDING_PROVIDER", "stub")).strip().lower(),
            "api_key": api_key,
            "base_url": str(
                runtime.get("embedding_base_url")
                or os.getenv("EMBEDDING_BASE_URL")
                or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
            )
            .strip()
            .rstrip("/"),
            "model": str(
                runtime.get("embedding_model")
                or os.getenv("EMBEDDING_MODEL")
                or os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
            ).strip(),
        }

    def _stub(self, text: str) -> list[float]:
        values = [0.0] * self.dim
        normalized = str(text or "").lower()
        tokens: list[str] = []
        tokens.extend(re.findall(r"\d+(?:\.\d+)+", normalized))
        tokens.extend(re.findall(r"[a-z0-9]+", normalized))
        tokens.extend(ch for ch in normalized if "\u4e00" <= ch <= "\u9fff")
        if not tokens:
            tokens = ["__empty__"]

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if (digest[4] & 1) == 0 else -1.0
            weight = 1.0 + min(len(token), 8) / 8.0
            values[idx] += sign * weight

        norm = math.sqrt(sum(v * v for v in values))
        if norm > 0:
            values = [v / norm for v in values]
        return values

    def _openai_compatible(self, text: str, api_key: str, base_url: str, model: str) -> list[float]:
        if not api_key:
            raise RuntimeError("embedding_api_key is required when embedding_provider=openai")
        resp = requests.post(
            f"{base_url}/embeddings",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "input": text},
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        body = resp.json()
        vec = (((body.get("data") or [{}])[0]).get("embedding") or [])
        if not isinstance(vec, list) or not vec:
            raise RuntimeError("empty embedding response")
        return [float(x) for x in vec]

    def embed_text(self, text: str, runtime_config: dict[str, Any] | None = None) -> list[float]:
        cfg = self._resolve_runtime(runtime_config=runtime_config)
        provider = cfg["provider"] or "stub"
        try:
            if provider == "openai":
                return self._openai_compatible(
                    text=text,
                    api_key=cfg["api_key"],
                    base_url=cfg["base_url"],
                    model=cfg["model"],
                )
        except Exception:  # noqa: BLE001
            return self._stub(text)
        return self._stub(text)


class RuntimeRerankClient:
    def __init__(self) -> None:
        self.timeout_s = float(os.getenv("RERANK_HTTP_TIMEOUT_S", "20"))

    def _normalize_token(self, raw: str) -> str:
        token = str(raw or "").strip()
        if token.lower().startswith("bearer "):
            token = token.split(" ", 1)[1].strip()
        return token

    def _resolve_runtime(self, runtime_config: dict[str, Any] | None = None) -> dict[str, str]:
        runtime = runtime_config or {}
        api_key = self._normalize_token(str(runtime.get("rerank_api_key") or ""))
        return {
            "provider": str(runtime.get("rerank_provider") or os.getenv("RERANK_PROVIDER", "stub")).strip().lower(),
            "api_key": api_key,
            "base_url": str(
                runtime.get("rerank_base_url") or os.getenv("RERANK_BASE_URL") or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
            )
            .strip()
            .rstrip("/"),
            "model": str(runtime.get("rerank_model") or os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")).strip(),
        }

    def _hit_text(self, hit: dict[str, Any]) -> str:
        payload = (hit or {}).get("payload") or {}
        return str(payload.get("chunk_text") or payload.get("excerpt") or "").strip()

    def _fallback(self, question: str, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        tokens = set(re.findall(r"[A-Za-z0-9\u4e00-\u9fa5]+", question.lower()))
        if not tokens:
            return hits

        def score(item: dict[str, Any]) -> float:
            text = self._hit_text(item).lower()
            if not text:
                return 0.0
            overlap = sum(1 for t in tokens if t in text)
            base = float((item or {}).get("score") or 0.0)
            return overlap * 100.0 + base

        return sorted(hits, key=score, reverse=True)

    def _parse_ranked_indices(self, content: str, size: int) -> list[int]:
        try:
            parsed = json.loads(content)
        except Exception:  # noqa: BLE001
            return []
        indices = parsed
        if isinstance(parsed, dict):
            indices = parsed.get("indices") or parsed.get("ranked_indices") or []
        if not isinstance(indices, list):
            return []
        output: list[int] = []
        for item in indices:
            try:
                idx = int(item)
            except Exception:  # noqa: BLE001
                continue
            if 0 <= idx < size and idx not in output:
                output.append(idx)
        return output

    def _parse_rerank_response(self, body: dict[str, Any], size: int) -> list[int]:
        candidates = body.get("results")
        if not isinstance(candidates, list):
            candidates = body.get("data")
        if not isinstance(candidates, list):
            candidates = body.get("output")
        if not isinstance(candidates, list):
            return []

        pairs: list[tuple[int, float]] = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            idx_raw = item.get("index")
            if idx_raw is None:
                idx_raw = item.get("document_index")
            if idx_raw is None:
                idx_raw = item.get("id")
            try:
                idx = int(idx_raw)
            except Exception:  # noqa: BLE001
                continue
            if not (0 <= idx < size):
                continue
            score_raw = item.get("relevance_score")
            if score_raw is None:
                score_raw = item.get("score")
            if score_raw is None:
                score_raw = item.get("relevance")
            try:
                score = float(score_raw) if score_raw is not None else 0.0
            except Exception:  # noqa: BLE001
                score = 0.0
            pairs.append((idx, score))

        if not pairs:
            return []
        pairs.sort(key=lambda x: x[1], reverse=True)
        ranked: list[int] = []
        for idx, _ in pairs:
            if idx not in ranked:
                ranked.append(idx)
        return ranked

    def _native_rerank(self, question: str, hits: list[dict[str, Any]], cfg: dict[str, str]) -> list[dict[str, Any]]:
        docs = [self._hit_text(h)[:1200] for h in hits]
        if not any(docs):
            return hits
        payload = {
            "model": cfg["model"],
            "query": question,
            "documents": docs,
            "top_n": len(docs),
            "return_documents": False,
        }

        base_url = cfg["base_url"].rstrip("/")
        endpoints = [f"{base_url}/rerank"]
        if not base_url.endswith("/v1"):
            endpoints.append(f"{base_url}/v1/rerank")

        last_error: Exception | None = None
        body: dict[str, Any] = {}
        for endpoint in endpoints:
            try:
                resp = requests.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=self.timeout_s,
                )
                resp.raise_for_status()
                body = resp.json()
                ranked = self._parse_rerank_response(body, len(hits))
                if ranked:
                    rest = [i for i in range(len(hits)) if i not in ranked]
                    ordered = ranked + rest
                    return [hits[i] for i in ordered]
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue

        if last_error is not None:
            raise last_error
        # Endpoint responded but result shape is unsupported: use local fallback.
        return self._fallback(question=question, hits=hits)

    def rerank_hits(self, question: str, hits: list[dict[str, Any]], runtime_config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if len(hits) <= 1:
            return hits
        cfg = self._resolve_runtime(runtime_config=runtime_config)
        if cfg["provider"] == "openai" and cfg["api_key"]:
            try:
                return self._native_rerank(question=question, hits=hits, cfg=cfg)
            except Exception:  # noqa: BLE001
                return self._fallback(question=question, hits=hits)
        if cfg["provider"] in {"local", "stub", ""}:
            return self._fallback(question=question, hits=hits)
        return hits


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


def _payload_search_text(payload: dict[str, Any]) -> str:
    return " ".join(
        [
            str(payload.get("chunk_text") or ""),
            str(payload.get("excerpt") or ""),
            str(payload.get("doc_name") or ""),
            str(payload.get("chapter_id") or ""),
        ]
    ).lower()


def _extract_query_terms(query: str) -> list[str]:
    q = str(query or "").lower()
    terms: list[str] = []
    terms.extend(re.findall(r"\d+(?:\.\d+)+", q))
    terms.extend(re.findall(r"[a-z0-9]{2,}", q))
    terms.extend(re.findall(r"[\u4e00-\u9fff]{2,8}", q))
    # Deduplicate while preserving order.
    out: list[str] = []
    seen: set[str] = set()
    for t in terms:
        x = t.strip()
        if not x or x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _keyword_score(text: str, terms: list[str]) -> float:
    if not text or not terms:
        return 0.0
    score = 0.0
    for term in terms:
        count = text.count(term)
        if count <= 0:
            continue
        # Reward exact sparse match; damp repeated counts.
        score += (1.0 + min(len(term), 12) / 12.0) * math.log1p(count)
    return score


def _fuse_rrf(result_lists: list[list[dict[str, Any]]], limit: int, k: int = 60) -> list[dict[str, Any]]:
    acc: dict[str, dict[str, Any]] = {}
    for lst in result_lists:
        for rank, item in enumerate(lst, start=1):
            key = str(item.get("id") or "")
            if not key:
                continue
            rrf = 1.0 / (k + rank)
            prev = acc.get(key)
            if prev is None:
                acc[key] = {"item": item, "score": rrf}
            else:
                prev["score"] = float(prev["score"]) + rrf
                # Keep stronger payload object when available.
                if (item.get("payload") or {}) and not (prev["item"].get("payload") or {}):
                    prev["item"] = item
    ordered = sorted(acc.values(), key=lambda x: float(x["score"]), reverse=True)
    return [x["item"] for x in ordered[:limit]]


def _merge_filters(
    base_filter: dict[str, Any] | None,
    extra_filter: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not base_filter and not extra_filter:
        return None
    must: list[dict[str, Any]] = []
    if isinstance(base_filter, dict):
        must.extend(list(base_filter.get("must") or []))
    if isinstance(extra_filter, dict):
        must.extend(list(extra_filter.get("must") or []))
    return {"must": must} if must else None


def _to_citation(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "doc_name": payload.get("doc_name", ""),
        "page_start": payload.get("page_start"),
        "page_end": payload.get("page_end"),
        "excerpt": payload.get("excerpt", ""),
        "chunk_text": payload.get("chunk_text", ""),
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
    top_k: int = 16,
    runtime_config: dict[str, Any] | None = None,
    search_filter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parsed_filter, vector_query_text = parse_filter_spec(question, entity_index)
    filter_json = _merge_filters(parsed_filter, search_filter)
    query_vector = SimpleEmbeddingClient().embed_text(vector_query_text, runtime_config=runtime_config)
    vector_top_k = max(top_k, int(os.getenv("HYBRID_VECTOR_TOP_K", "24")))
    keyword_top_k = max(top_k, int(os.getenv("HYBRID_KEYWORD_TOP_K", "24")))
    fused_limit = max(top_k * 2, int(os.getenv("HYBRID_FUSED_TOP_K", "40")))

    vector_hits = repo.search(query_vector=query_vector, filter_json=filter_json, limit=vector_top_k)
    keyword_hits: list[dict[str, Any]] = []
    if str(os.getenv("HYBRID_KEYWORD_ENABLED", "1")).strip() not in {"0", "false", "False"}:
        try:
            keyword_hits = repo.keyword_search(query_text=question, filter_json=filter_json, limit=keyword_top_k)
        except Exception:  # noqa: BLE001
            keyword_hits = []

    if keyword_hits:
        hits = _fuse_rrf([vector_hits, keyword_hits], limit=fused_limit)
    else:
        hits = vector_hits
    hits = RuntimeRerankClient().rerank_hits(question=question, hits=hits, runtime_config=runtime_config)
    hits = hits[:top_k]

    citations = [_to_citation((h or {}).get("payload", {})) for h in hits]
    return {
        "hits": hits,
        "citations": citations,
        "filter_json": filter_json,
    }
