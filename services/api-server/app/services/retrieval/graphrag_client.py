"""Youtu GraphRAG sidecar client."""

from __future__ import annotations

import os
from typing import Any

import requests


class GraphRAGClient:
    def __init__(self, base_url: str | None = None, timeout_s: float | None = None) -> None:
        self.base_url = str(base_url or os.getenv("YOUTU_GRAPHRAG_BASE_URL", "http://graphrag:8092")).strip().rstrip("/")
        self.timeout_s = float(timeout_s or os.getenv("YOUTU_GRAPHRAG_TIMEOUT_S", "3.0"))

    def search(self, question: str, top_n: int = 50) -> list[dict[str, Any]]:
        q = str(question or "").strip()
        if not q:
            return []
        payload = {"query": q, "top_n": max(1, int(top_n))}
        resp = requests.post(f"{self.base_url}/search", json=payload, timeout=self.timeout_s)
        resp.raise_for_status()
        body = resp.json()
        rows = body.get("hits")
        if not isinstance(rows, list):
            rows = body.get("result") if isinstance(body.get("result"), list) else []
        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "doc_id": str(row.get("doc_id") or "").strip(),
                    "page_no": int(row.get("page_no") or row.get("page") or 0),
                    "excerpt": str(row.get("excerpt") or row.get("text") or "").strip(),
                    "score": float(row.get("score") or 0.0),
                    "source": "graphrag",
                    "source_path": str(row.get("source_path") or "").strip(),
                    "doc_name": str(row.get("doc_name") or "").strip(),
                }
            )
        return [item for item in out if item["doc_id"] and item["page_no"] > 0]

