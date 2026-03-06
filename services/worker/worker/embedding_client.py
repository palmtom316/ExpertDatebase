"""Embedding client with provider fallback and deterministic local stub."""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
from typing import Any

import requests

_log = logging.getLogger(__name__)


class EmbeddingClient:
    def __init__(self, dim: int = 1024) -> None:
        env_dim = str(os.getenv("EMBEDDING_DIM") or os.getenv("EMBEDDING_DIMENSIONS") or "").strip()
        if env_dim:
            self.dim = int(env_dim)
            self._stub_dim_pinned = True
        else:
            self.dim = int(dim)
            self._stub_dim_pinned = False
        self.provider = os.getenv("EMBEDDING_PROVIDER", "auto").strip().lower()
        self.timeout_s = float(os.getenv("EMBEDDING_HTTP_TIMEOUT_S", "15"))
        self._cached_remote_stub_dim: int | None = None
        self._remote_stub_dim_probed = False
        self._last_call_meta: dict[str, object] = {}

    def _default_base_url(self, provider: str) -> str:
        if provider == "siliconflow":
            return "https://api.siliconflow.cn/v1"
        return "https://api.openai.com/v1"

    def _default_model(self, provider: str) -> str:
        if provider == "siliconflow":
            return "Qwen/Qwen3-Embedding-8B"
        return "text-embedding-3-small"

    def _normalize_token(self, raw: str) -> str:
        token = str(raw or "").strip()
        if token.lower().startswith("bearer "):
            token = token.split(" ", 1)[1].strip()
        return token

    def _resolve_dimensions(self, runtime_config: dict[str, Any] | None = None) -> int | None:
        runtime = runtime_config or {}
        raw = str(runtime.get("embedding_dimensions") or os.getenv("EMBEDDING_DIMENSIONS") or "").strip()
        if not raw:
            return None
        try:
            value = int(raw)
        except Exception:  # noqa: BLE001
            return None
        return value if value > 0 else None

    def _resolve_runtime(self, runtime_config: dict | None = None) -> dict[str, str | int | None]:
        runtime = runtime_config or {}
        api_key = self._normalize_token(
            str(
                runtime.get("embedding_api_key")
                or os.getenv("EMBEDDING_API_KEY")
                or os.getenv("OPENAI_API_KEY")
                or ""
            )
        )
        provider = str(runtime.get("embedding_provider") or self.provider or "auto").strip().lower()
        if provider == "auto":
            provider = "openai" if api_key else "stub"
        default_base_url = self._default_base_url(provider)
        default_model = self._default_model(provider)
        return {
            "provider": provider,
            "api_key": api_key,
            "base_url": str(
                runtime.get("embedding_base_url")
                or os.getenv("EMBEDDING_BASE_URL")
                or os.getenv("OPENAI_BASE_URL", default_base_url)
            )
            .strip()
            .rstrip("/"),
            "model": str(
                runtime.get("embedding_model")
                or os.getenv("EMBEDDING_MODEL")
                or os.getenv("OPENAI_EMBEDDING_MODEL", default_model)
            ).strip(),
            "dimensions": self._resolve_dimensions(runtime_config=runtime),
        }

    def _is_strict_fallback(self, runtime_config: dict | None = None) -> bool:
        runtime = runtime_config or {}
        strict_raw = str(runtime.get("embedding_fallback_strict") or os.getenv("EMBEDDING_FALLBACK_STRICT", "")).strip().lower()
        if strict_raw:
            return strict_raw in {"1", "true", "yes", "on"}
        app_env = str(os.getenv("APP_ENV", "development")).strip().lower()
        return app_env in {"prod", "production"}

    def pop_last_call_meta(self) -> dict[str, object]:
        meta = dict(self._last_call_meta or {})
        self._last_call_meta = {}
        return meta

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
                    if isinstance(value, dict):
                        size = int(value.get("size") or 0)
                        if size > 0:
                            return size
            return None
        except Exception:
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

    def _stub_many(self, texts: list[str]) -> list[list[float]]:
        return [self._stub(text) for text in texts]

    def _openai_compatible(
        self,
        input_value: str | list[str],
        api_key: str,
        base_url: str,
        model: str,
        dimensions: int | None = None,
    ) -> list[float] | list[list[float]]:
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for embedding provider")
        payload: dict[str, Any] = {"model": model, "input": input_value}
        if dimensions is not None:
            payload["dimensions"] = int(dimensions)

        resp = requests.post(
            f"{base_url}/embeddings",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data") or []
        if not isinstance(data, list) or not data:
            raise RuntimeError("empty embedding response")
        vectors: list[list[float]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            vec = item.get("embedding") or []
            if not isinstance(vec, list) or not vec:
                raise RuntimeError("empty embedding vector")
            vectors.append([float(x) for x in vec])
        if not vectors:
            raise RuntimeError("empty embedding response")
        if isinstance(input_value, str):
            return vectors[0]
        return vectors

    def embed_texts(self, texts: list[str], runtime_config: dict | None = None) -> list[list[float]]:
        normalized_texts = [str(text or "") for text in texts]
        if not normalized_texts:
            return []
        cfg = self._resolve_runtime(runtime_config=runtime_config)
        provider = str(cfg["provider"] or "stub")
        strict_fallback = self._is_strict_fallback(runtime_config=runtime_config)
        self._last_call_meta = {
            "provider": provider,
            "model": cfg.get("model", ""),
            "used_stub": False,
            "fallback_reason": "",
            "strict": bool(strict_fallback),
            "item_count": len(normalized_texts),
            "request_count": 1,
            "dimensions": cfg.get("dimensions"),
        }

        try:
            if provider in {"openai", "siliconflow"}:
                vectors = self._openai_compatible(
                    input_value=normalized_texts,
                    api_key=str(cfg["api_key"] or ""),
                    base_url=str(cfg["base_url"] or ""),
                    model=str(cfg["model"] or ""),
                    dimensions=cfg.get("dimensions") if isinstance(cfg.get("dimensions"), int) else None,
                )
                if not isinstance(vectors, list) or not vectors:
                    raise RuntimeError("empty embedding response")
                if vectors and isinstance(vectors[0], float):
                    vectors = [vectors]
                if len(vectors) != len(normalized_texts):
                    raise RuntimeError(
                        f"embedding response count mismatch: expected {len(normalized_texts)} got {len(vectors)}"
                    )
                self._last_call_meta.update({"used_stub": False, "fallback_reason": ""})
                return vectors
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
            return self._stub_many(normalized_texts)
        self._last_call_meta.update(
            {
                "used_stub": True,
                "fallback_reason": "provider_stub" if provider == "stub" else "provider_non_openai",
            }
        )
        return self._stub_many(normalized_texts)

    def embed_text(self, text: str, runtime_config: dict | None = None) -> list[float]:
        vectors = self.embed_texts([text], runtime_config=runtime_config)
        return vectors[0] if vectors else self._stub(text)
