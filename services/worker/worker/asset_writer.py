"""Asset persistence adapters (MVP)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonlAssetWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, assets: list[dict[str, Any]]) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            for item in assets:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
