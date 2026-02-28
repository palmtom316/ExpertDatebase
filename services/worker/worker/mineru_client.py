"""MinerU client adapter (MVP stub)."""

from __future__ import annotations

import os
from typing import Any

import requests


class MinerUClient:
    def parse_pdf(self, pdf_bytes: bytes, runtime_config: dict[str, Any] | None = None) -> dict[str, Any]:
        runtime = runtime_config or {}
        base = str(runtime.get("mineru_api_base") or os.getenv("MINERU_API_BASE", "")).strip().rstrip("/")
        api_key = str(runtime.get("mineru_api_key") or os.getenv("MINERU_API_KEY", "")).strip()
        if base:
            headers: dict[str, str] = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            resp = requests.post(
                f"{base}/parse",
                headers=headers,
                files={"file": ("upload.pdf", pdf_bytes, "application/pdf")},
                timeout=float(os.getenv("MINERU_HTTP_TIMEOUT_S", "30")),
            )
            resp.raise_for_status()
            payload = resp.json()
            if isinstance(payload, dict) and isinstance(payload.get("pages"), list):
                return payload

        text = pdf_bytes.decode("utf-8", errors="ignore").strip()
        if not text:
            text = "上传文档内容。"
        body = text[:2000]
        return {
            "pages": [
                {
                    "page_no": 1,
                    "blocks": [
                        {"type": "title", "text": "第一章 自动解析"},
                        {"type": "paragraph", "text": body},
                    ],
                    "tables": [],
                }
            ]
        }
