"""MinerU client adapter (MVP stub)."""

from __future__ import annotations

from typing import Any


class MinerUClient:
    def parse_pdf(self, pdf_bytes: bytes) -> dict[str, Any]:
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
