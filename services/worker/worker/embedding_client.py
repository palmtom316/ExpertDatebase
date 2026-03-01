"""Embedding client with provider fallback and deterministic local stub."""

from __future__ import annotations

import hashlib
import math
import os
import re

import requests


class EmbeddingClient:
    def __init__(self, dim: int = 1024) -> None:
        self.dim = int(os.getenv("EMBEDDING_DIM", str(dim)))
        self.provider = os.getenv("EMBEDDING_PROVIDER", "auto").strip().lower()
        self.timeout_s = float(os.getenv("EMBEDDING_HTTP_TIMEOUT_S", "15"))

    def _normalize_token(self, raw: str) -> str:
        token = str(raw or "").strip()
        if token.lower().startswith("bearer "):
            token = token.split(" ", 1)[1].strip()
        return token

    def _resolve_runtime(self, runtime_config: dict | None = None) -> dict[str, str]:
        runtime = runtime_config or {}
        api_key = self._normalize_token(str(runtime.get("embedding_api_key") or ""))
        provider = str(runtime.get("embedding_provider") or self.provider or "auto").strip().lower()
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
            raise RuntimeError("OPENAI_API_KEY is required for embedding provider")

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

    def embed_text(self, text: str, runtime_config: dict | None = None) -> list[float]:
        cfg = self._resolve_runtime(runtime_config=runtime_config)
        provider = cfg["provider"]

        try:
            if provider == "openai":
                return self._openai_compatible(
                    text=text,
                    api_key=cfg["api_key"],
                    base_url=cfg["base_url"],
                    model=cfg["model"],
                )
        except Exception as exc:  # noqa: BLE001
            print("embedding fallback to stub", str(exc))
        return self._stub(text)
