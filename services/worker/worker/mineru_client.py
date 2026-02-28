"""MinerU client adapter (MVP stub)."""

from __future__ import annotations

from typing import Any


class MinerUClient:
    def parse_pdf(self, pdf_bytes: bytes) -> dict[str, Any]:
        # Stub for local development: real integration to be added.
        return {"pages": []}
