"""Simple JSON registry for documents and versions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JSONDocRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text('{"documents": [], "versions": []}', encoding="utf-8")

    def _read(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def add_document(self, doc: dict[str, Any], version: dict[str, Any]) -> None:
        payload = self._read()
        payload["documents"].append(doc)
        payload["versions"].append(version)
        self._write(payload)
