"""Embedding client with provider fallback and deterministic local stub."""

from __future__ import annotations

import hashlib
import os

import requests


class EmbeddingClient:
    def __init__(self, dim: int = 8) -> None:
        self.dim = int(os.getenv("EMBEDDING_DIM", str(dim)))
        self.provider = os.getenv("EMBEDDING_PROVIDER", "auto").strip().lower()
        self.timeout_s = float(os.getenv("EMBEDDING_HTTP_TIMEOUT_S", "15"))

    def _stub(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values: list[float] = []
        for i in range(self.dim):
            b = digest[i]
            values.append((b / 255.0) * 2 - 1)
        return values

    def _openai_compatible(self, text: str) -> list[float]:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for embedding provider")

        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
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

    def embed_text(self, text: str) -> list[float]:
        provider = self.provider
        if provider == "auto":
            provider = "openai" if os.getenv("OPENAI_API_KEY") else "stub"

        try:
            if provider == "openai":
                return self._openai_compatible(text)
        except Exception as exc:  # noqa: BLE001
            print("embedding fallback to stub", str(exc))
        return self._stub(text)
