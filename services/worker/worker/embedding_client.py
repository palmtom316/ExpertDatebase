"""Embedding client (deterministic local stub for MVP)."""

from __future__ import annotations

import hashlib


class EmbeddingClient:
    def __init__(self, dim: int = 8) -> None:
        self.dim = dim

    def embed_text(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values = []
        for i in range(self.dim):
            b = digest[i]
            values.append((b / 255.0) * 2 - 1)
        return values
