"""Sirchmunk sparse sidecar client with simple circuit breaker."""

from __future__ import annotations

import os
import time
from typing import Any

import requests


class SirchmunkClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout_s: float | None = None,
        fail_threshold: int | None = None,
        cooldown_seconds: int | None = None,
    ) -> None:
        self.base_url = str(base_url or os.getenv("SIRCHMUNK_BASE_URL", "http://sirchmunk:8091")).strip().rstrip("/")
        self.timeout_s = float(timeout_s or os.getenv("SIRCHMUNK_TIMEOUT_S", "2.5"))
        self.fail_threshold = max(1, int(fail_threshold or os.getenv("SIRCHMUNK_FAIL_THRESHOLD", "3")))
        self.cooldown_seconds = max(1, int(cooldown_seconds or os.getenv("SIRCHMUNK_COOLDOWN_SECONDS", "30")))
        self._consecutive_failures = 0
        self._opened_until = 0.0

    def _is_open(self) -> bool:
        return time.time() < self._opened_until

    def _normalize_hit(self, item: dict[str, Any]) -> dict[str, Any]:
        page_no = item.get("page_no")
        if page_no is None:
            page_no = item.get("page")
        return {
            "doc_id": str(item.get("doc_id") or "").strip(),
            "page_no": int(page_no or 0),
            "excerpt": str(item.get("excerpt") or item.get("text") or "").strip(),
            "score": float(item.get("score") or 0.0),
            "source": "sirchmunk",
            "source_path": str(item.get("source_path") or "").strip(),
            "doc_name": str(item.get("doc_name") or "").strip(),
        }

    def search(self, query_text: str, top_n: int = 200) -> list[dict[str, Any]]:
        if self._is_open():
            raise RuntimeError("sirchmunk circuit open")
        q = str(query_text or "").strip()
        if not q:
            return []
        payload = {"query": q, "top_n": max(1, int(top_n))}
        try:
            resp = requests.post(f"{self.base_url}/search", json=payload, timeout=self.timeout_s)
            resp.raise_for_status()
            body = resp.json()
            hits_raw = body.get("hits")
            if not isinstance(hits_raw, list):
                hits_raw = body.get("result") if isinstance(body.get("result"), list) else []
            out = [self._normalize_hit(item) for item in hits_raw if isinstance(item, dict)]
            out = [item for item in out if item["doc_id"] and item["page_no"] > 0]
            self._consecutive_failures = 0
            self._opened_until = 0.0
            return out
        except Exception:  # noqa: BLE001
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.fail_threshold:
                self._opened_until = time.time() + self.cooldown_seconds
            raise RuntimeError("sidecar down")

