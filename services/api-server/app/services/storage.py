"""Storage adapters."""

from __future__ import annotations

from pathlib import Path


class LocalObjectStorage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, object_key: str, data: bytes) -> None:
        target = self.root / object_key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def exists(self, object_key: str) -> bool:
        return (self.root / object_key).exists()
