"""Hybrid search service with in-memory and Qdrant HTTP backends."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import time
from typing import Any, Protocol
from uuid import UUID, uuid5, NAMESPACE_URL

import requests

from app.services.filter_parser import extract_clause_ids, parse_filter_spec
from app.services.retrieval.graphrag_client import GraphRAGClient
from app.services.retrieval.sparse.pg_bm25 import PgBM25SparseRetriever
from app.services.retrieval.sparse.sirchmunk_client import SirchmunkClient
from app.services.retrieval.structured_lookup import StructuredLookupService

_log = logging.getLogger(__name__)


class SearchRepo(Protocol):
    def search(self, query_vector: list[float], filter_json: dict[str, Any] | None, limit: int = 5) -> list[dict[str, Any]]:
        raise NotImplementedError

    def keyword_search(self, query_text: str, filter_json: dict[str, Any] | None, limit: int = 20) -> list[dict[str, Any]]:
        raise NotImplementedError

    def fetch_by_filter(self, filter_json: dict[str, Any] | None, limit: int = 20) -> list[dict[str, Any]]:
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

    def fetch_by_filter(self, filter_json: dict[str, Any] | None, limit: int = 20) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for r in self._records:
            payload = r.get("payload") or {}
            if not _match_filter(payload, filter_json):
                continue
            out.append({"id": r.get("id"), "score": r.get("score"), "payload": payload})
            if len(out) >= limit:
                break
        return out

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
        self._last_search_degraded_reason: str | None = None

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
        self._last_search_degraded_reason = None
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
                self._last_search_degraded_reason = "collection_not_found"
                return []
            # Runtime embedding model may temporarily mismatch the indexed vector
            # dimension (e.g., user switched provider/model). Degrade to no hits
            # instead of surfacing a 500 to chat.
            if self._is_vector_mismatch_error(
                status_code=int(getattr(resp, "status_code", 0) or 0),
                body=str(getattr(resp, "text", "") or ""),
            ):
                self._last_search_degraded_reason = "vector_dimension_mismatch"
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

    def fetch_by_filter(self, filter_json: dict[str, Any] | None, limit: int = 20) -> list[dict[str, Any]]:
        points = self._scroll_payloads(filter_json=filter_json, limit=max(1, int(limit)))
        hits: list[dict[str, Any]] = []
        for p in points[: max(1, int(limit))]:
            hits.append(
                {
                    "id": p.get("id"),
                    "score": p.get("score"),
                    "payload": p.get("payload", {}),
                }
            )
        return hits

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
    def __init__(self, dim: int | None = None) -> None:
        env_dim = str(os.getenv("EMBEDDING_DIM") or "").strip()
        if dim is not None:
            self.dim = int(dim)
            self._stub_dim_pinned = True
        elif env_dim:
            self.dim = int(env_dim)
            self._stub_dim_pinned = True
        else:
            self.dim = 1024
            self._stub_dim_pinned = False
        self.timeout_s = float(os.getenv("EMBEDDING_HTTP_TIMEOUT_S", "15"))
        self._cached_remote_stub_dim: int | None = None
        self._remote_stub_dim_probed = False
        self._last_call_meta: dict[str, Any] = {}

    def _normalize_token(self, raw: str) -> str:
        token = str(raw or "").strip()
        if token.lower().startswith("bearer "):
            token = token.split(" ", 1)[1].strip()
        return token

    def _resolve_runtime(self, runtime_config: dict[str, Any] | None = None) -> dict[str, str]:
        runtime = runtime_config or {}
        api_key = self._normalize_token(
            str(
                runtime.get("embedding_api_key")
                or os.getenv("EMBEDDING_API_KEY")
                or os.getenv("OPENAI_API_KEY")
                or ""
            )
        )
        provider = str(runtime.get("embedding_provider") or os.getenv("EMBEDDING_PROVIDER", "auto")).strip().lower()
        if provider == "auto":
            provider = "openai" if api_key else "stub"
        return {
            "provider": provider,
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

    def pop_last_call_meta(self) -> dict[str, Any]:
        meta = dict(self._last_call_meta or {})
        self._last_call_meta = {}
        return meta

    def _is_strict_fallback(self, runtime_config: dict[str, Any] | None = None) -> bool:
        runtime = runtime_config or {}
        strict_raw = str(runtime.get("embedding_fallback_strict") or os.getenv("EMBEDDING_FALLBACK_STRICT", "")).strip().lower()
        if strict_raw:
            return strict_raw in {"1", "true", "yes", "on"}
        app_env = str(os.getenv("APP_ENV", "development")).strip().lower()
        return app_env in {"prod", "production"}

    def _resolve_remote_stub_dim(self) -> int | None:
        endpoint = str(os.getenv("VECTORDB_ENDPOINT") or "").strip()
        if not endpoint:
            return None
        if not endpoint.startswith("http"):
            endpoint = f"http://{endpoint}"
        collection = str(os.getenv("QDRANT_COLLECTION") or "chunks_v1").strip() or "chunks_v1"
        vector_name = str(os.getenv("QDRANT_VECTOR_NAME") or "text_embedding").strip() or "text_embedding"
        try:
            resp = requests.get(
                f"{endpoint.rstrip('/')}/collections/{collection}",
                timeout=min(self.timeout_s, 5.0),
            )
            resp.raise_for_status()
            raw = resp.json()
            body = raw if isinstance(raw, dict) else {}
            vectors = ((((body or {}).get("result") or {}).get("config") or {}).get("params") or {}).get("vectors")
            if isinstance(vectors, dict):
                named = vectors.get(vector_name)
                if isinstance(named, dict):
                    size = int(named.get("size") or 0)
                    if size > 0:
                        return size
                if "size" in vectors:
                    size = int(vectors.get("size") or 0)
                    if size > 0:
                        return size
                for value in vectors.values():
                    if isinstance(value, dict) and int(value.get("size") or 0) > 0:
                        return int(value.get("size"))
            return None
        except Exception as exc:  # noqa: BLE001
            _log.debug("embedding_stub_dim_resolve_failed error=%s", str(exc))
            return None

    def _stub_dim(self) -> int:
        if self._stub_dim_pinned:
            return max(1, int(self.dim))
        if self._cached_remote_stub_dim is not None:
            return self._cached_remote_stub_dim
        if self._remote_stub_dim_probed:
            return max(1, int(self.dim))
        self._remote_stub_dim_probed = True
        remote_dim = self._resolve_remote_stub_dim()
        if remote_dim and remote_dim > 0:
            self._cached_remote_stub_dim = int(remote_dim)
            return self._cached_remote_stub_dim
        return max(1, int(self.dim))

    def _stub(self, text: str) -> list[float]:
        dim = self._stub_dim()
        values = [0.0] * dim
        normalized = str(text or "").lower()
        tokens: list[str] = []
        tokens.extend(re.findall(r"\d+(?:\.\d+)+", normalized))
        tokens.extend(re.findall(r"[a-z0-9]+", normalized))
        tokens.extend(ch for ch in normalized if "\u4e00" <= ch <= "\u9fff")
        if not tokens:
            tokens = ["__empty__"]

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % dim
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
        strict_fallback = self._is_strict_fallback(runtime_config=runtime_config)
        self._last_call_meta = {
            "provider": provider,
            "model": cfg.get("model", ""),
            "used_stub": False,
            "fallback_reason": "",
            "strict": bool(strict_fallback),
        }
        try:
            if provider == "openai":
                vec = self._openai_compatible(
                    text=text,
                    api_key=cfg["api_key"],
                    base_url=cfg["base_url"],
                    model=cfg["model"],
                )
                self._last_call_meta.update({"used_stub": False, "fallback_reason": ""})
                return vec
        except Exception as exc:  # noqa: BLE001
            fallback_reason = f"openai_failed:{type(exc).__name__}"
            self._last_call_meta.update(
                {
                    "used_stub": True,
                    "fallback_reason": fallback_reason,
                    "error": str(exc),
                }
            )
            _log.warning(
                "embedding_failed provider=%s model=%s strict=%s fallback=stub error=%s",
                provider,
                cfg.get("model"),
                strict_fallback,
                str(exc),
            )
            if strict_fallback:
                raise RuntimeError(f"embedding failed in strict mode: {exc}") from exc
            return self._stub(text)
        self._last_call_meta.update(
            {
                "used_stub": True,
                "fallback_reason": "provider_stub" if provider == "stub" else "provider_non_openai",
            }
        )
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
        api_key = self._normalize_token(
            str(
                runtime.get("rerank_api_key")
                or os.getenv("RERANK_API_KEY")
                or os.getenv("OPENAI_API_KEY")
                or ""
            )
        )
        provider = str(runtime.get("rerank_provider") or os.getenv("RERANK_PROVIDER", "auto")).strip().lower()
        if provider == "auto":
            provider = "openai" if api_key else "stub"
        return {
            "provider": provider,
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
        text = str(payload.get("chunk_text") or payload.get("excerpt") or "").strip()
        include_meta_raw = str(os.getenv("RERANK_INCLUDE_METADATA", "1")).strip().lower()
        include_meta = include_meta_raw not in {"0", "false", "no", "off", ""}
        if not include_meta:
            return text

        clause_id = str(payload.get("clause_id") or payload.get("clause_no") or payload.get("article_no") or "").strip()
        parts: list[str] = []
        for key in ("doc_name", "standard_no", "doc_type", "version_id", "source_type", "route"):
            value = str(payload.get(key) or "").strip()
            if value:
                parts.append(f"{key}={value}")
        if clause_id:
            parts.append(f"clause_id={clause_id}")
        if not parts:
            return text
        meta = " | ".join(parts)
        if not text:
            return f"[{meta}]"
        return f"[{meta}]\n{text}"

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
        if value is None and key == "clause_no":
            value = payload.get("clause_id")
        if value is None and key == "clause_id":
            value = payload.get("clause_no")
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
            try:
                numeric_value = float(value)
            except Exception:  # noqa: BLE001
                return False
            gte = cond["range"].get("gte")
            lte = cond["range"].get("lte")
            gt = cond["range"].get("gt")
            lt = cond["range"].get("lt")
            if gte is not None and numeric_value < float(gte):
                return False
            if lte is not None and numeric_value > float(lte):
                return False
            if gt is not None and numeric_value <= float(gt):
                return False
            if lt is not None and numeric_value >= float(lt):
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


_CN_STOP_TERMS = {
    "哪些",
    "哪些规定",
    "有哪些",
    "有什么",
    "规定",
    "要求",
    "相关",
    "有关",
    "请问",
    "一下",
    "一下子",
    "说明",
    "什么",
    "怎么",
    "如何",
    "应当",
    "应该",
    "是否",
}
_CN_STOP_CHARS = set("的了吗呢吧啊呀和及并且或与在对将把为于被就都与其")
_STANDARD_QUERY_PAT = re.compile(
    r"(?<![A-Za-z0-9])((?:GB|DL/T|DL|NB/T|IEC|ISO)\s*[-A-Z]*\s*\d{2,6}(?:-\d{4})?)(?![A-Za-z0-9])",
    flags=re.IGNORECASE,
)
_DOC_TYPE_QUERY_HINTS: dict[str, tuple[str, ...]] = {
    "规范规程": ("规范", "规程", "标准", "强制性条文", "国标", "gb", "dl/t", "nb/t", "iec", "iso"),
    "投标文件": ("投标", "招标", "商务条款", "技术条款", "评标"),
    "公司资质": ("公司资质", "企业资质", "许可证", "营业执照"),
    "人员资质": ("人员资质", "项目经理证", "注册证", "职称"),
    "公司业绩": ("公司业绩", "类似业绩", "合同业绩"),
    "人员业绩": ("人员业绩", "个人业绩"),
}
_LOW_QUALITY_CACHE: dict[str, Any] = {"expires_at": 0.0, "doc_ids": set(), "version_ids": set()}


def _clean_query_for_terms(query: str) -> str:
    q = str(query or "").lower()
    q = re.sub(r"(?<!\d)\d{1,2}(?:\.\d+){1,4}(?:\([0-9A-Za-z]+\))?(?!\d)", " ", q)
    q = re.sub(r"(回复|回答|查询到|没查询到|没有查询到|为什么|还是|但是|却)", " ", q)
    q = re.sub(r"(有哪些规定|有哪(?:些)?规定|有哪些|有哪|哪些|规定|要求|什么|如何|怎么|请问)", " ", q)
    return re.sub(r"\s+", "", q)


def _split_cn_run(run: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    for ch in run:
        if ch in _CN_STOP_CHARS:
            if len(buf) >= 2:
                parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    if len(buf) >= 2:
        parts.append("".join(buf))
    return parts


def _valid_cn_term(term: str) -> bool:
    t = str(term or "").strip()
    if len(t) < 2:
        return False
    if t in _CN_STOP_TERMS:
        return False
    if re.search(r"(哪些|有哪|规定|要求|什么|如何|怎么|请问)", t):
        return False
    if len(t) <= 3 and re.search(r"[有哪些]", t):
        return False
    if all(ch in _CN_STOP_CHARS for ch in t):
        return False
    return True


def _extract_query_terms(query: str) -> list[str]:
    q = _clean_query_for_terms(query)
    terms: list[str] = []
    terms.extend(re.findall(r"\d+(?:\.\d+)+", q))
    terms.extend(re.findall(r"[a-z0-9]{2,}", q))
    cn_runs = re.findall(r"[\u4e00-\u9fff]{2,36}", q)
    for run in cn_runs:
        segments = _split_cn_run(run)
        if not segments:
            segments = [run]
        for seg in segments:
            seg_len = len(seg)
            if seg_len <= 8 and _valid_cn_term(seg):
                terms.append(seg)
            for n in (2, 3, 4):
                if seg_len < n:
                    continue
                for i in range(0, seg_len - n + 1):
                    gram = seg[i : i + n]
                    if _valid_cn_term(gram):
                        terms.append(gram)
    # Deduplicate while preserving order.
    out: list[str] = []
    seen: set[str] = set()
    for t in terms:
        x = t.strip()
        if not x or x in seen:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]+", x) and not _valid_cn_term(x):
            continue
        seen.add(x)
        out.append(x)
    return out


def _extract_standard_tokens(query: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for m in _STANDARD_QUERY_PAT.finditer(str(query or "")):
        raw = str(m.group(1) or "").strip().upper()
        if not raw:
            continue
        compact = re.sub(r"\s+", "", raw)
        for token in (raw, compact):
            if not token or token in seen:
                continue
            seen.add(token)
            out.append(token)
    return out


def _query_doc_type_prior(question: str) -> str | None:
    q = str(question or "").strip()
    if not q:
        return None
    for doc_type, hints in _DOC_TYPE_QUERY_HINTS.items():
        if any(hint in q for hint in hints):
            return doc_type
    return None


def _normalize_compact_upper(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().upper())


def _is_precision_query(question: str, standard_tokens: list[str], clause_tokens: list[str]) -> bool:
    if clause_tokens:
        return True
    if not standard_tokens:
        return False
    if _is_listing_query(question):
        return False
    max_len = max(12, _safe_int(os.getenv("HYBRID_ROUTE_PRECISION_MAX_QUERY_LEN", "48"), 48))
    compact_len = len(re.sub(r"\s+", "", str(question or "")))
    return compact_len <= max_len


def _build_route_plan(
    question: str,
    filter_json: dict[str, Any] | None,
    standard_tokens: list[str],
    clause_tokens: list[str],
    table_query: bool,
) -> dict[str, Any]:
    has_doc_scope = _has_doc_scope_filter(filter_json)
    plan: dict[str, Any] = {
        "enabled": _env_enabled("HYBRID_ROUTE_GATING_ENABLED", default=True),
        "precision_query": False,
        "has_doc_scope": has_doc_scope,
        "table_query": bool(table_query),
        "enable_dense": True,
        "enable_sparse": True,
        "enable_keyword": True,
        "enable_structured": True,
        "enable_graphrag": True,
        "reason": "default",
    }
    if not bool(plan["enabled"]):
        plan["reason"] = "router_disabled"
        return plan

    precision = _is_precision_query(question=question, standard_tokens=standard_tokens, clause_tokens=clause_tokens)
    plan["precision_query"] = precision
    if precision:
        plan["reason"] = "precision"
        if (
            not has_doc_scope
            and not table_query
            and _env_enabled("HYBRID_ROUTE_DISABLE_SPARSE_ON_PRECISION", default=True)
        ):
            plan["enable_sparse"] = False
            plan["reason"] = "precision_disable_sparse"
        if _env_enabled("HYBRID_ROUTE_DISABLE_GRAPHRAG_ON_PRECISION", default=True):
            plan["enable_graphrag"] = False
    if table_query and _env_enabled("HYBRID_ROUTE_TABLE_FORCE_SPARSE", default=True):
        plan["enable_sparse"] = True
    if has_doc_scope and _env_enabled("HYBRID_ROUTE_DOC_SCOPE_FORCE_SPARSE", default=True):
        plan["enable_sparse"] = True
    return plan


def _hit_matches_precision(
    payload: dict[str, Any],
    standard_tokens: list[str],
    clause_tokens: list[str],
) -> bool:
    if standard_tokens:
        token_fields = [
            _normalize_compact_upper(payload.get("standard_no")),
            _normalize_compact_upper(payload.get("doc_name")),
            _normalize_compact_upper(payload.get("chunk_text") or payload.get("excerpt")),
        ]
        norm_tokens = [_normalize_compact_upper(item) for item in standard_tokens if str(item or "").strip()]
        if not any(token and any(token in field for field in token_fields if field) for token in norm_tokens):
            return False
    if clause_tokens:
        clause_payload = str(payload.get("clause_id") or payload.get("clause_no") or payload.get("article_no") or "").strip()
        if clause_payload:
            if not any(
                clause_payload == clause
                or clause_payload.startswith(f"{clause}.")
                or clause.startswith(f"{clause_payload}.")
                for clause in clause_tokens
            ):
                return False
        else:
            text = str(payload.get("chunk_text") or payload.get("excerpt") or "")
            if not any(clause in text for clause in clause_tokens):
                return False
    return True


def _lexical_gate_hits(question: str, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(hits) <= 1:
        return hits
    terms = _extract_query_terms(question)
    if not terms:
        return hits

    min_ratio = _safe_float(os.getenv("HYBRID_ROUTE_LEXICAL_MIN_RATIO", "0.25"), 0.25)
    min_ratio = min(1.0, max(0.0, min_ratio))
    min_abs = max(0.0, _safe_float(os.getenv("HYBRID_ROUTE_LEXICAL_MIN_ABS", "0.3"), 0.3))
    fallback_keep = max(1, _safe_int(os.getenv("HYBRID_ROUTE_LEXICAL_MIN_KEEP", "3"), 3))

    scored: list[tuple[float, dict[str, Any]]] = []
    top_score = 0.0
    for hit in hits:
        payload = (hit or {}).get("payload") or {}
        lexical = _keyword_score(_payload_search_text(payload), terms)
        top_score = max(top_score, lexical)
        scored.append((lexical, hit))

    threshold = max(min_abs, top_score * min_ratio)
    kept = [item for lexical, item in scored if lexical > 0 and lexical >= threshold]
    if kept:
        return kept
    return list(hits[:fallback_keep])


def _apply_route_gate(
    question: str,
    route: str,
    hits: list[dict[str, Any]],
    route_plan: dict[str, Any],
    standard_tokens: list[str],
    clause_tokens: list[str],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    before = len(hits)
    if before <= 1:
        return hits, {"before": before, "after": before}

    gated = list(hits)
    if (
        bool(route_plan.get("precision_query"))
        and route in {"sparse", "keyword", "filter_keyword"}
        and _env_enabled("HYBRID_ROUTE_GATE_PRECISION_HITS", default=True)
    ):
        filtered = [
            hit
            for hit in gated
            if _hit_matches_precision(
                payload=((hit or {}).get("payload") or {}),
                standard_tokens=standard_tokens,
                clause_tokens=clause_tokens,
            )
        ]
        if filtered:
            gated = filtered
        elif _env_enabled("HYBRID_ROUTE_GATE_DROP_ALL_ON_MISMATCH", default=False):
            gated = []

    if (
        route in {"sparse", "keyword", "filter_keyword"}
        and _env_enabled("HYBRID_ROUTE_LEXICAL_GATE_ENABLED", default=True)
    ):
        gated = _lexical_gate_hits(question=question, hits=gated)

    return gated, {"before": before, "after": len(gated)}


def _doc_scope_from_filter(filter_json: dict[str, Any] | None) -> tuple[set[str], set[str]]:
    doc_ids: set[str] = set()
    version_ids: set[str] = set()
    if not isinstance(filter_json, dict):
        return doc_ids, version_ids
    for cond in list(filter_json.get("must") or []):
        key = str(cond.get("key") or "").strip()
        if key not in {"doc_id", "version_id"}:
            continue
        match = cond.get("match") or {}
        values: list[str] = []
        if match.get("value") is not None:
            values.append(str(match.get("value")))
        if isinstance(match.get("any"), list):
            values.extend([str(v) for v in match.get("any") if str(v or "").strip()])
        if key == "doc_id":
            doc_ids.update(v.strip() for v in values if v.strip())
        else:
            version_ids.update(v.strip() for v in values if v.strip())
    return doc_ids, version_ids


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return default


def _low_quality_targets() -> tuple[set[str], set[str]]:
    ttl_s = max(10, _safe_int(os.getenv("HYBRID_LOW_QUALITY_CACHE_TTL_S", "60"), 60))
    now = time.monotonic()
    if now < float(_LOW_QUALITY_CACHE.get("expires_at") or 0):
        return set(_LOW_QUALITY_CACHE.get("doc_ids") or set()), set(_LOW_QUALITY_CACHE.get("version_ids") or set())

    doc_ids: set[str] = set()
    version_ids: set[str] = set()
    if not _env_enabled("HYBRID_LOW_QUALITY_DOC_PENALTY_ENABLED", default=True):
        _LOW_QUALITY_CACHE.update({"expires_at": now + ttl_s, "doc_ids": doc_ids, "version_ids": version_ids})
        return doc_ids, version_ids

    try:
        from app.services.doc_registry import build_doc_registry_from_env

        registry = build_doc_registry_from_env()
        scan_limit = max(100, _safe_int(os.getenv("HYBRID_LOW_QUALITY_SCAN_LIMIT", "2000"), 2000))
        rows = registry.list_versions(statuses=["processed"], limit=scan_limit)
        for row in rows:
            if not isinstance(row, dict):
                continue
            notes = row.get("notes") if isinstance(row.get("notes"), dict) else {}
            quality = notes.get("quality_gate") if isinstance(notes, dict) and isinstance(notes.get("quality_gate"), dict) else {}
            grade = str((quality or {}).get("grade") or "").strip().upper()
            score = _safe_float((quality or {}).get("score"), 0.0)
            text_len = _safe_int((quality or {}).get("text_len"), 0)
            chunk_count = _safe_int((notes or {}).get("chunks"), 0)
            dropped_short = _safe_int(((notes or {}).get("chunk_filter_stats") or {}).get("dropped_short"), 0)
            low_quality = (
                grade in {"D", "F"}
                or (grade == "C" and (text_len <= 200 or chunk_count <= 3 or dropped_short >= max(chunk_count, 2)))
                or (score > 0 and score < 20 and chunk_count <= 4)
            )
            if not low_quality:
                continue
            doc_id = str(row.get("doc_id") or "").strip()
            version_id = str(row.get("id") or "").strip()
            if doc_id:
                doc_ids.add(doc_id)
            if version_id:
                version_ids.add(version_id)
    except Exception as exc:  # noqa: BLE001
        _log.debug("low_quality_targets_load_failed error=%s", str(exc))

    _LOW_QUALITY_CACHE.update({"expires_at": now + ttl_s, "doc_ids": doc_ids, "version_ids": version_ids})
    return doc_ids, version_ids


def _drop_low_quality_sparse_hits(
    sparse_hits: list[dict[str, Any]],
    selected_doc_ids: set[str],
    selected_version_ids: set[str],
) -> list[dict[str, Any]]:
    if not sparse_hits:
        return sparse_hits
    if selected_doc_ids or selected_version_ids:
        return sparse_hits
    low_docs, low_versions = _low_quality_targets()
    if not low_docs and not low_versions:
        return sparse_hits
    kept: list[dict[str, Any]] = []
    for hit in sparse_hits:
        payload = (hit or {}).get("payload") or {}
        doc_id = str(payload.get("doc_id") or "").strip()
        version_id = str(payload.get("version_id") or "").strip()
        if (doc_id and doc_id in low_docs) or (version_id and version_id in low_versions):
            continue
        kept.append(hit)
    return kept


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


def _post_keyword_boost_hits(question: str, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(hits) <= 1:
        return hits
    terms = _extract_query_terms(question)
    standard_tokens = _extract_standard_tokens(question)
    clause_tokens = extract_clause_ids(question)
    if not terms and not standard_tokens and not clause_tokens:
        return hits

    question_norm = re.sub(r"\s+", "", str(question or "").lower())
    table_query = _is_table_query(question)
    listing_query = _is_listing_query(question)
    query_doc_type = _query_doc_type_prior(question)
    low_docs, low_versions = _low_quality_targets()
    scored: list[tuple[float, dict[str, Any]]] = []

    for idx, hit in enumerate(hits):
        payload = (hit or {}).get("payload") or {}
        text = _payload_search_text(payload)
        text_norm = re.sub(r"\s+", "", text.lower())
        doc_name_upper = str(payload.get("doc_name") or "").strip().upper()
        doc_type = str(payload.get("doc_type") or "").strip()
        doc_id = str(payload.get("doc_id") or "").strip()
        version_id = str(payload.get("version_id") or "").strip()
        standard_no_upper = str(payload.get("standard_no") or "").strip().upper()
        clause_payload = str(payload.get("clause_id") or payload.get("clause_no") or payload.get("article_no") or "").strip()

        lexical = _keyword_score(text, terms) if terms else 0.0
        exact = 0.0
        if question_norm and len(question_norm) <= 32 and question_norm in text_norm:
            exact += 6.0
        for term in terms:
            if len(term) >= 3 and term in text:
                exact += 0.3

        for standard in standard_tokens:
            if standard_no_upper == standard:
                exact += 8.0
            elif standard and standard in standard_no_upper:
                exact += 5.0
            elif standard and standard in doc_name_upper:
                exact += 4.0
            elif standard and standard.lower() in text:
                exact += 2.0

        for clause in clause_tokens:
            if not clause:
                continue
            if clause_payload == clause:
                exact += 6.0
            elif clause_payload and (clause_payload.startswith(f"{clause}.") or clause.startswith(f"{clause_payload}.")):
                exact += 3.0
            elif clause in text:
                exact += 1.5

        if table_query:
            source_type = str(payload.get("source_type") or "").strip().lower()
            page_type = str(payload.get("page_type") or "").strip().lower()
            if source_type in {"table_row", "cross_page_table_row"}:
                exact += 4.0
            if "table" in page_type:
                exact += 2.0
        source_type = str(payload.get("source_type") or "").strip().lower()
        route = str(payload.get("route") or "").strip().lower()
        if source_type == "structured_fact":
            exact += 3.0
        if route == "structured":
            exact += 1.5
        if route == "keyword":
            exact += 1.0
        if route == "filter_keyword":
            exact += 1.2
        if route == "sparse":
            exact += 0.8
            if not doc_name_upper:
                exact -= 2.5
        if query_doc_type and doc_type == query_doc_type:
            exact += 2.5
        if (doc_id and doc_id in low_docs) or (version_id and version_id in low_versions):
            exact -= float(os.getenv("HYBRID_LOW_QUALITY_DOC_PENALTY", "6.0"))
        if listing_query and source_type == "section_summary":
            # Listing-style questions should prioritize concrete clause body.
            exact -= 1.2

        base = float((hit or {}).get("score") or 0.0)
        final_score = lexical * 5.0 + exact + base * 0.03 - idx * 1e-4
        scored.append((final_score, hit))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored]


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


def _has_doc_scope_filter(filter_json: dict[str, Any] | None) -> bool:
    if not isinstance(filter_json, dict):
        return False
    for cond in list(filter_json.get("must") or []):
        key = str(cond.get("key") or "").strip()
        if key not in {"doc_id", "version_id"}:
            continue
        match = cond.get("match") or {}
        if match.get("value") is not None:
            return True
        if isinstance(match.get("any"), list) and match.get("any"):
            return True
    return False


def _filter_keyword_fallback_hits(
    question: str,
    repo: SearchRepo,
    filter_json: dict[str, Any] | None,
    limit: int,
) -> list[dict[str, Any]]:
    terms = _extract_query_terms(question)
    if not terms:
        return []
    scan_limit = max(limit * 20, int(os.getenv("HYBRID_FILTER_FALLBACK_SCAN_MAX", "800")))
    base_hits = _fetch_hits_by_filter(
        repo=repo,
        filter_json=filter_json,
        limit=scan_limit,
        fallback_query=question,
    )
    scored: list[tuple[float, dict[str, Any]]] = []
    for hit in base_hits:
        payload = (hit or {}).get("payload") or {}
        if not isinstance(payload, dict):
            continue
        text = _payload_search_text(payload)
        lexical = _keyword_score(text=text, terms=terms)
        if lexical <= 0:
            continue
        boosted = lexical * 5.0 + float((hit or {}).get("score") or 0.0) * 0.05
        payload.setdefault("route", "filter_keyword")
        scored.append(
            (
                boosted,
                {
                    "id": hit.get("id"),
                    "score": boosted,
                    "payload": payload,
                },
            )
        )
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[: max(1, int(limit))]]


def _remove_clause_constraints(filter_json: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(filter_json, dict):
        return None
    must = list(filter_json.get("must") or [])
    kept = [cond for cond in must if str(cond.get("key") or "") not in {"clause_id", "clause_no"}]
    return {"must": kept} if kept else None


def _is_listing_query(question: str) -> bool:
    q = str(question or "").strip().lower()
    if not q:
        return False
    hints = [
        "有哪些",
        "包括哪些",
        "包含哪些",
        "列出",
        "清单",
        "哪些要求",
        "what are",
        "which are",
        "list",
        "include",
    ]
    return any(token in q for token in hints)


def _chapter_prefixes_from_question(question: str, clause_hits: list[str]) -> list[str]:
    q = str(question or "").lower()
    chapter_hint = any(token in q for token in ["章", "章节", "chapter"])
    if not clause_hits or (not chapter_hint and not _is_listing_query(question)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in clause_hits:
        clause = re.sub(r"\([0-9A-Za-z]+\)$", "", str(raw or "").strip())
        if not clause:
            continue
        parts = clause.split(".")
        if len(parts) < 2:
            continue
        # Treat chapter-like query as two-level prefix (e.g. 4.3 -> 4.3.*).
        prefix = f"{parts[0]}.{parts[1]}"
        if prefix in seen:
            continue
        seen.add(prefix)
        out.append(prefix)
    return out


def _filter_hits_by_clause_prefix(hits: list[dict[str, Any]], prefixes: list[str]) -> list[dict[str, Any]]:
    if not hits or not prefixes:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hit in hits:
        payload = (hit or {}).get("payload") or {}
        clause_raw = str(payload.get("clause_id") or payload.get("clause_no") or "").strip()
        clause = re.sub(r"\([0-9A-Za-z]+\)$", "", clause_raw)
        text = _payload_search_text(payload)
        matched = False
        for p in prefixes:
            if clause:
                if clause == p or clause.startswith(f"{p}."):
                    matched = True
                    break
                # When clause id exists but prefix differs, reject directly to avoid cross-chapter noise.
                continue
            pat = re.compile(rf"(?<!\d){re.escape(p)}(?:\.\d+)*(?:\([0-9A-Za-z]+\))?(?!\d)")
            if pat.search(text):
                matched = True
                break
        if not matched:
            continue
        hit_id = str((hit or {}).get("id") or "")
        if hit_id and hit_id in seen:
            continue
        if hit_id:
            seen.add(hit_id)
        out.append(hit)
    return out


def _dedupe_hits_by_id(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hit in hits:
        hid = str((hit or {}).get("id") or "")
        if hid and hid in seen:
            continue
        if hid:
            seen.add(hid)
        out.append(hit)
    return out


def _is_table_query(question: str) -> bool:
    q = str(question or "").strip().lower()
    if not q:
        return False
    hints = ["表", "表格", "续表", "跨页", "行", "列", "参数表", "清单", "table", "rows", "columns", "schedule"]
    if any(token in q for token in hints):
        return True

    if re.search(r"\d+(?:\.\d+)?\s*(kv|mva|kw|mw|v|a|hz|pa|mpa|mm|cm|m|km|℃|万元|万|亿|%|％)", q, flags=re.IGNORECASE):
        return True

    return False


def _table_query_extra_filter(enabled: bool) -> dict[str, Any] | None:
    if not enabled:
        return None
    return {
        "must": [
            {
                "key": "source_type",
                "match": {"any": ["table_row", "cross_page_table_row"]},
            }
        ]
    }


def _to_citation(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "doc_name": payload.get("doc_name", ""),
        "doc_id": payload.get("doc_id", ""),
        "page_start": payload.get("page_start"),
        "page_end": payload.get("page_end"),
        "excerpt": payload.get("excerpt", ""),
        "chunk_text": payload.get("chunk_text", ""),
        "route": payload.get("route", "dense"),
        "source_type": payload.get("source_type", ""),
        "page_type": payload.get("page_type", ""),
        "table_id": payload.get("table_id"),
        "row_index": payload.get("row_index"),
        "clause_id": payload.get("clause_id") or payload.get("clause_no"),
        "table_repr": payload.get("table_repr"),
    }


def _fetch_hits_by_filter(
    repo: SearchRepo,
    filter_json: dict[str, Any] | None,
    limit: int,
    fallback_query: str = "",
) -> list[dict[str, Any]]:
    fetch_fn = getattr(repo, "fetch_by_filter", None)
    if callable(fetch_fn):
        try:
            return fetch_fn(filter_json=filter_json, limit=limit) or []
        except Exception:  # noqa: BLE001
            pass
    if fallback_query:
        try:
            return repo.keyword_search(query_text=fallback_query, filter_json=filter_json, limit=limit)
        except Exception:  # noqa: BLE001
            return []
    return []


def _attach_explanation_siblings(
    citations: list[dict[str, Any]],
    repo: SearchRepo,
    filter_json: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    stats = {
        "clause_candidates": 0,
        "clause_lookups": 0,
        "clause_hits": 0,
        "attached": 0,
    }
    if not citations or not _env_enabled("HYBRID_ATTACH_EXPLANATION", default=False):
        return citations, stats

    per_clause_limit = max(1, int(os.getenv("HYBRID_EXPLANATION_PER_CLAUSE", "1")))
    seen_keys: set[tuple[str, Any, Any, str, str]] = set()
    out: list[dict[str, Any]] = []
    searched_clause: set[str] = set()
    clauses_with_hits: set[str] = set()
    anchor_clauses: set[str] = {
        str(item.get("clause_id") or "").strip()
        for item in citations
        if str(item.get("source_type") or "").strip().lower() != "explanation" and str(item.get("clause_id") or "").strip()
    }

    def _add(c: dict[str, Any], is_attached: bool = False) -> bool:
        key = (
            str(c.get("doc_id") or "").strip(),
            c.get("page_start"),
            c.get("page_end"),
            str(c.get("source_type") or "").strip(),
            str(c.get("clause_id") or "").strip(),
        )
        if key in seen_keys:
            return False
        seen_keys.add(key)
        out.append(c)
        if is_attached:
            stats["attached"] += 1
        return True

    for citation in citations:
        source_type = str(citation.get("source_type") or "").strip().lower()
        clause_id = str(citation.get("clause_id") or "").strip()
        is_existing_sibling = source_type == "explanation" and bool(clause_id) and clause_id in anchor_clauses
        current = citation
        if is_existing_sibling:
            current = dict(citation)
            current["route"] = "explanation_sibling"
        _add(current, is_attached=is_existing_sibling)
        if not clause_id:
            continue
        stats["clause_candidates"] += 1
        if clause_id in searched_clause:
            continue
        searched_clause.add(clause_id)
        stats["clause_lookups"] += 1

        sibling_filter = _merge_filters(
            filter_json,
            {
                "must": [
                    {"key": "source_type", "match": {"value": "explanation"}},
                    {"key": "clause_id", "match": {"value": clause_id}},
                ]
            },
        )
        sibling_hits = _fetch_hits_by_filter(
            repo=repo,
            filter_json=sibling_filter,
            limit=per_clause_limit,
            fallback_query=clause_id,
        )

        for hit in sibling_hits:
            payload = (hit or {}).get("payload") or {}
            if not isinstance(payload, dict):
                continue
            payload["route"] = "explanation_sibling"
            if _add(_to_citation(payload), is_attached=True):
                clauses_with_hits.add(clause_id)

    stats["clause_hits"] = len(clauses_with_hits)
    return out, stats


def _env_enabled(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw not in {"0", "false", "no", "off", ""}


def _allow_keyword_search(repo: SearchRepo) -> bool:
    if not _env_enabled("HYBRID_KEYWORD_ENABLED", default=True):
        return False
    if isinstance(repo, QdrantHttpRepo):
        return _env_enabled("ENABLE_QDRANT_SCROLL_KEYWORD", default=True)
    return True


def _route_hit_id(route: str, doc_id: str, page_no: int, excerpt: str) -> str:
    digest = hashlib.sha256(f"{route}|{doc_id}|{page_no}|{excerpt}".encode("utf-8")).hexdigest()[:12]
    return f"{route}:{doc_id}:{page_no}:{digest}"


def _normalize_route_hits(items: list[dict[str, Any]], route: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        doc_id = str(item.get("doc_id") or "").strip()
        page_no = int(item.get("page_no") or 0)
        excerpt = str(item.get("excerpt") or item.get("chunk_text") or "").strip()
        if not doc_id or page_no <= 0:
            continue
        doc_name = str(item.get("doc_name") or "").strip()
        hit_id = _route_hit_id(route=route, doc_id=doc_id, page_no=page_no, excerpt=excerpt)
        payload = {
            "doc_id": doc_id,
            "doc_name": doc_name,
            "page_start": page_no,
            "page_end": page_no,
            "excerpt": excerpt,
            "chunk_text": str(item.get("chunk_text") or excerpt),
            "route": route,
            "source_path": str(item.get("source_path") or ""),
            "source_type": str(item.get("source_type") or ""),
            "page_type": str(item.get("page_type") or ""),
            "version_id": str(item.get("version_id") or ""),
            "doc_type": str(item.get("doc_type") or ""),
            "standard_no": str(item.get("standard_no") or ""),
            "table_id": item.get("table_id"),
            "row_index": item.get("row_index"),
            "clause_id": item.get("clause_id") or item.get("clause_no"),
            "clause_no": item.get("clause_no") or item.get("clause_id"),
        }
        hits.append({"id": hit_id, "score": float(item.get("score") or 0.0), "payload": payload})
    return hits


def _should_trigger_graphrag(question: str, current_hits: list[dict[str, Any]]) -> bool:
    q = str(question or "")
    if not q:
        return False
    connector_count = sum(1 for token in ["同时", "并且", "且", "分别", "关系", "关联", "and", "or"] if token in q)
    condition_count = len(re.findall(r"\d{1,2}(?:\.\d+){1,4}", q))
    condition_count += len(re.findall(r"[A-Z]{1,6}(?:-[A-Z0-9]{1,10}){2,}", q))
    if connector_count >= 1 and condition_count >= 1:
        return True
    if connector_count >= 2:
        return True
    if len(current_hits) < 3:
        return True
    return False


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
    parsed_filter, sparse_query, dense_query_text = parse_filter_spec(question, entity_index)
    filter_json = _merge_filters(parsed_filter, search_filter)
    standard_tokens = _extract_standard_tokens(question)
    query_doc_type = _query_doc_type_prior(question)
    if query_doc_type and not _has_doc_scope_filter(filter_json):
        filter_json = _merge_filters(
            filter_json,
            {"must": [{"key": "doc_type", "match": {"value": query_doc_type}}]},
        )
    clause_hits = extract_clause_ids(question)
    table_query = _is_table_query(question)
    route_plan = _build_route_plan(
        question=question,
        filter_json=filter_json,
        standard_tokens=standard_tokens,
        clause_tokens=clause_hits,
        table_query=table_query,
    )
    chapter_prefixes = _chapter_prefixes_from_question(question=question, clause_hits=clause_hits)
    if chapter_prefixes:
        chapter_filter = _remove_clause_constraints(filter_json)
        chapter_hits: list[dict[str, Any]] = []
        chapter_limit = max(top_k * 8, int(os.getenv("HYBRID_CHAPTER_TOP_K", "96")))
        try:
            chapter_hits = repo.keyword_search(
                query_text=f"{question} {' '.join(chapter_prefixes)}",
                filter_json=chapter_filter,
                limit=chapter_limit,
            )
        except Exception:  # noqa: BLE001
            chapter_hits = []
        # Loose pass: prefix-only recall helps pull same-chapter tables/continuations.
        try:
            chapter_hits_loose = repo.keyword_search(
                query_text=" ".join(chapter_prefixes),
                filter_json=chapter_filter,
                limit=chapter_limit,
            )
        except Exception:  # noqa: BLE001
            chapter_hits_loose = []
        chapter_hits = _dedupe_hits_by_id(chapter_hits + chapter_hits_loose)
        chapter_hits = _filter_hits_by_clause_prefix(chapter_hits, chapter_prefixes)
        if chapter_hits:
            for hit in chapter_hits:
                payload = (hit or {}).get("payload")
                if isinstance(payload, dict):
                    payload.setdefault("route", "chapter_prefix")
            hits = chapter_hits
            if _env_enabled("ENABLE_RERANK", default=True):
                hits = RuntimeRerankClient().rerank_hits(question=question, hits=hits, runtime_config=runtime_config)
            if _env_enabled("HYBRID_POST_KEYWORD_BOOST", default=True):
                hits = _post_keyword_boost_hits(question=question, hits=hits)
            hits = hits[:top_k]
            citations = [_to_citation((h or {}).get("payload", {})) for h in hits]
            citations, explanation_stats = _attach_explanation_siblings(
                citations=citations,
                repo=repo,
                filter_json=chapter_filter,
            )
            return {
                "hits": hits,
                "citations": citations,
                "filter_json": chapter_filter,
                "debug": {
                    "route_counts": {"chapter_prefix": len(chapter_hits)},
                    "degraded_routes": {},
                    "explanation_attach": explanation_stats,
                },
            }

    if clause_hits:
        clause_id_filter = _merge_filters(
            filter_json,
            {"must": [{"key": "clause_id", "match": {"any": clause_hits}}]},
        )
        clause_no_filter = _merge_filters(
            filter_json,
            {"must": [{"key": "clause_no", "match": {"any": clause_hits}}]},
        )
        clause_hits_exact: list[dict[str, Any]] = []
        try:
            clause_hits_exact = repo.keyword_search(
                query_text=" ".join(clause_hits),
                filter_json=clause_id_filter,
                limit=max(top_k * 4, int(os.getenv("HYBRID_CLAUSE_TOP_K", "48"))),
            )
        except Exception:  # noqa: BLE001
            clause_hits_exact = []
        if not clause_hits_exact:
            try:
                clause_hits_exact = repo.keyword_search(
                    query_text=" ".join(clause_hits),
                    filter_json=clause_no_filter,
                    limit=max(top_k * 4, int(os.getenv("HYBRID_CLAUSE_TOP_K", "48"))),
                )
            except Exception:  # noqa: BLE001
                clause_hits_exact = []
        if clause_hits_exact:
            filtered_clause_hits: list[dict[str, Any]] = []
            for hit in clause_hits_exact:
                payload = (hit or {}).get("payload")
                if isinstance(payload, dict):
                    payload.setdefault("route", "clause_exact")
                    source_type = str(payload.get("source_type") or "").strip().lower()
                    if source_type != "explanation":
                        filtered_clause_hits.append(hit)
            # Keep explanation chunks as sibling attachments when possible to avoid
            # clause route being dominated by explanation text.
            hits = filtered_clause_hits or clause_hits_exact
            if _env_enabled("ENABLE_RERANK", default=True):
                hits = RuntimeRerankClient().rerank_hits(question=question, hits=hits, runtime_config=runtime_config)
            if _env_enabled("HYBRID_POST_KEYWORD_BOOST", default=True):
                hits = _post_keyword_boost_hits(question=question, hits=hits)
            hits = hits[:top_k]
            citations = [_to_citation((h or {}).get("payload", {})) for h in hits]
            citations, explanation_stats = _attach_explanation_siblings(
                citations=citations,
                repo=repo,
                filter_json=clause_no_filter,
            )
            return {
                "hits": hits,
                "citations": citations,
                "filter_json": clause_no_filter,
                "debug": {
                    "route_counts": {"clause_exact": len(clause_hits_exact)},
                    "degraded_routes": {},
                    "explanation_attach": explanation_stats,
                },
            }
        # If exact route yields nothing, keep clause fallback filter for dense/keyword routes.
        filter_json = clause_no_filter

    embedding_client = SimpleEmbeddingClient()
    query_vector = embedding_client.embed_text(dense_query_text, runtime_config=runtime_config)
    embedding_meta = embedding_client.pop_last_call_meta()
    table_sparse_enabled = table_query and _env_enabled("HYBRID_TABLE_QUERY_SPARSE_FILTER", default=False)
    table_sparse_filter = _merge_filters(filter_json, _table_query_extra_filter(table_sparse_enabled))
    vector_top_k = max(top_k, int(os.getenv("HYBRID_VECTOR_TOP_K", "48")))
    keyword_top_k = max(4, int(os.getenv("HYBRID_KEYWORD_TOP_K", "24")))
    if _is_listing_query(question):
        keyword_top_k = max(keyword_top_k, int(os.getenv("HYBRID_KEYWORD_TOP_K_LISTING", "64")))
    fused_limit = max(top_k * 3, int(os.getenv("HYBRID_FUSED_TOP_K", "80")))
    sparse_top_k = max(top_k, int(os.getenv("HYBRID_SPARSE_TOP_K", "24")))
    structured_top_k = max(top_k, int(os.getenv("HYBRID_STRUCTURED_TOP_K", "24")))

    vector_hits = repo.search(query_vector=query_vector, filter_json=filter_json, limit=vector_top_k)
    for hit in vector_hits:
        payload = (hit or {}).get("payload")
        if isinstance(payload, dict):
            payload.setdefault("route", "dense")

    route_lists: list[list[dict[str, Any]]] = [vector_hits]
    route_counts: dict[str, int] = {"dense": len(vector_hits), "keyword": 0, "filter_keyword": 0}
    route_gate_counts: dict[str, dict[str, int]] = {}
    degraded_routes: dict[str, str] = {}
    if bool(embedding_meta.get("used_stub")):
        degraded_routes["embedding"] = str(embedding_meta.get("fallback_reason") or "stub")
    if isinstance(repo, QdrantHttpRepo):
        reason = str(getattr(repo, "_last_search_degraded_reason", "") or "").strip()
        if reason:
            degraded_routes["dense"] = reason

    # Doc-scoped fallback: when vector route misses (e.g., embedding mismatch),
    # scan selected document points and rank by lexical overlap.
    filter_keyword_hits: list[dict[str, Any]] = []
    if not vector_hits and _has_doc_scope_filter(filter_json):
        try:
            filter_keyword_hits = _filter_keyword_fallback_hits(
                question=question,
                repo=repo,
                filter_json=filter_json,
                limit=max(keyword_top_k, top_k),
            )
        except Exception as exc:  # noqa: BLE001
            degraded_routes["filter_keyword"] = str(exc)
            filter_keyword_hits = []
    filter_keyword_hits, gate_stats = _apply_route_gate(
        question=question,
        route="filter_keyword",
        hits=filter_keyword_hits,
        route_plan=route_plan,
        standard_tokens=standard_tokens,
        clause_tokens=clause_hits,
    )
    route_gate_counts["filter_keyword"] = gate_stats
    if filter_keyword_hits:
        route_lists.append(filter_keyword_hits)
    route_counts["filter_keyword"] = len(filter_keyword_hits)

    sparse_candidates: list[dict[str, Any]] = []
    if bool(route_plan.get("enable_sparse", True)) and _env_enabled("ENABLE_PG_BM25", default=True):
        try:
            sparse_candidates.extend(
                PgBM25SparseRetriever().search(
                    query_text=sparse_query,
                    top_n=sparse_top_k,
                    filters=table_sparse_filter if table_sparse_enabled else filter_json,
                )
            )
        except Exception as exc:  # noqa: BLE001
            degraded_routes["pg_bm25"] = str(exc)

    if bool(route_plan.get("enable_sparse", True)) and _env_enabled("ENABLE_SIRCHMUNK", default=False):
        try:
            sparse_candidates.extend(
                SirchmunkClient().search(
                    query_text=sparse_query,
                    top_n=sparse_top_k,
                )
            )
        except Exception as exc:  # noqa: BLE001
            degraded_routes["sparse"] = str(exc)

    sparse_hits = _normalize_route_hits(sparse_candidates, route="sparse")
    scoped_doc_ids, scoped_version_ids = _doc_scope_from_filter(filter_json)
    sparse_hits = _drop_low_quality_sparse_hits(
        sparse_hits=sparse_hits,
        selected_doc_ids=scoped_doc_ids,
        selected_version_ids=scoped_version_ids,
    )
    sparse_hits, gate_stats = _apply_route_gate(
        question=question,
        route="sparse",
        hits=sparse_hits,
        route_plan=route_plan,
        standard_tokens=standard_tokens,
        clause_tokens=clause_hits,
    )
    route_gate_counts["sparse"] = gate_stats
    if sparse_hits:
        route_lists.append(sparse_hits)
    route_counts["sparse"] = len(sparse_hits)

    keyword_hits: list[dict[str, Any]] = []
    allow_keyword = _allow_keyword_search(repo)
    keyword_fallback_only = _env_enabled("HYBRID_KEYWORD_FALLBACK_ONLY", default=False)
    should_run_keyword = bool(route_plan.get("enable_keyword", True)) and allow_keyword and (
        not keyword_fallback_only or not sparse_hits
    )
    if should_run_keyword:
        try:
            keyword_hits = repo.keyword_search(query_text=question, filter_json=filter_json, limit=keyword_top_k)
            for hit in keyword_hits:
                payload = (hit or {}).get("payload")
                if isinstance(payload, dict):
                    payload.setdefault("route", "keyword")
        except Exception:  # noqa: BLE001
            keyword_hits = []
    keyword_hits, gate_stats = _apply_route_gate(
        question=question,
        route="keyword",
        hits=keyword_hits,
        route_plan=route_plan,
        standard_tokens=standard_tokens,
        clause_tokens=clause_hits,
    )
    route_gate_counts["keyword"] = gate_stats
    if keyword_hits:
        route_lists.append(keyword_hits)
    route_counts["keyword"] = len(keyword_hits)

    structured_hits: list[dict[str, Any]] = []
    if bool(route_plan.get("enable_structured", True)) and _env_enabled("ENABLE_STRUCTURED_LOOKUP", default=False):
        try:
            structured_hits = _normalize_route_hits(
                StructuredLookupService().lookup(question=question, top_n=structured_top_k),
                route="structured",
            )
        except Exception as exc:  # noqa: BLE001
            degraded_routes["structured"] = str(exc)
            structured_hits = []
    if structured_hits:
        route_lists.append(structured_hits)
    route_counts["structured"] = len(structured_hits)

    pre_graphrag_hits = _fuse_rrf(route_lists, limit=fused_limit)
    graphrag_hits: list[dict[str, Any]] = []
    if (
        bool(route_plan.get("enable_graphrag", True))
        and _env_enabled("ENABLE_YOUTU_GRAPHRAG", default=False)
        and _should_trigger_graphrag(
        question=question,
        current_hits=pre_graphrag_hits,
        )
    ):
        try:
            graphrag_hits = _normalize_route_hits(
                GraphRAGClient().search(question=question, top_n=structured_top_k),
                route="graphrag",
            )
        except Exception as exc:  # noqa: BLE001
            degraded_routes["graphrag"] = str(exc)
            graphrag_hits = []
    if graphrag_hits:
        route_lists.append(graphrag_hits)
    route_counts["graphrag"] = len(graphrag_hits)

    hits = _fuse_rrf(route_lists, limit=fused_limit)
    if _env_enabled("ENABLE_RERANK", default=True):
        hits = RuntimeRerankClient().rerank_hits(question=question, hits=hits, runtime_config=runtime_config)
    if _env_enabled("HYBRID_POST_KEYWORD_BOOST", default=True):
        hits = _post_keyword_boost_hits(question=question, hits=hits)
    hits = hits[:top_k]

    citations = [_to_citation((h or {}).get("payload", {})) for h in hits]
    citations, explanation_stats = _attach_explanation_siblings(citations=citations, repo=repo, filter_json=filter_json)
    return {
        "hits": hits,
        "citations": citations,
        "filter_json": filter_json,
        "debug": {
            "route_counts": route_counts,
            "route_gate_counts": route_gate_counts,
            "route_plan": route_plan,
            "degraded_routes": degraded_routes,
            "explanation_attach": explanation_stats,
            "embedding": embedding_meta,
        },
    }
