"""Entity index backed by PostgreSQL entity_dictionary table."""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from sqlalchemy import create_engine, text


class PgEntityIndex:
    """Read entity_dictionary from Postgres with a periodic refresh cache."""

    _REFRESH_INTERVAL_S = 300  # 5 minutes

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = str(database_url or os.getenv("DATABASE_URL") or "").strip()
        self._engine = create_engine(self._database_url, pool_pre_ping=True) if self._database_url else None
        self._lock = threading.RLock()
        self._cache: dict[str, dict[str, str]] = {}  # kind -> {name -> id}
        self._loaded_at: float = 0.0

    def _should_refresh(self) -> bool:
        return (time.monotonic() - self._loaded_at) > self._REFRESH_INTERVAL_S

    def _load(self) -> None:
        if not self._engine:
            return
        try:
            sql = text("SELECT entity_kind, entity_name, id FROM entity_dictionary ORDER BY entity_kind, entity_name")
            with self._engine.begin() as conn:
                rows = conn.execute(sql).mappings().all()
            cache: dict[str, dict[str, str]] = {}
            for row in rows:
                kind = str(row["entity_kind"] or "").strip().lower()
                name = str(row["entity_name"] or "").strip()
                eid = str(row["id"] or "").strip()
                if kind and name and eid:
                    cache.setdefault(kind, {})[name] = eid
            with self._lock:
                self._cache = cache
                self._loaded_at = time.monotonic()
        except Exception:  # noqa: BLE001
            pass

    def _ensure_loaded(self) -> None:
        if self._should_refresh():
            self._load()

    def match_names(self, kind: str, question: str) -> list[str]:
        self._ensure_loaded()
        k = str(kind or "").strip().lower()
        q = str(question or "")
        with self._lock:
            names = list(self._cache.get(k, {}).keys())
        return [name for name in names if name and name in q]

    def get_id(self, kind: str, name: str) -> str | None:
        self._ensure_loaded()
        k = str(kind or "").strip().lower()
        n = str(name or "").strip()
        with self._lock:
            return self._cache.get(k, {}).get(n)


class _FallbackEntityIndex:
    """No-op fallback when database is unavailable."""

    def match_names(self, kind: str, question: str) -> list[str]:
        return []

    def get_id(self, kind: str, name: str) -> str | None:
        return None


def build_entity_index_from_env() -> Any:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return PgEntityIndex(database_url=database_url)
    return _FallbackEntityIndex()
