"""Qdrant repository abstraction.

MVP uses in-memory storage while preserving query/filter interfaces.
"""

from __future__ import annotations

from typing import Any


class InMemoryQdrantRepo:
    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []

    def upsert(self, point_id: str, vector: list[float], payload: dict[str, Any]) -> None:
        self._records = [r for r in self._records if r["id"] != point_id]
        self._records.append({"id": point_id, "vector": vector, "payload": payload})

    def search(self, query_vector: list[float], filter_json: dict[str, Any] | None, limit: int = 5) -> list[dict[str, Any]]:
        results = [r for r in self._records if _match_filter(r["payload"], filter_json)]
        return results[:limit]


def _match_filter(payload: dict[str, Any], filter_json: dict[str, Any] | None) -> bool:
    if not filter_json:
        return True
    for cond in filter_json.get("must", []):
        key = cond["key"]
        if "match" in cond:
            target_any = cond["match"].get("any")
            target_value = cond["match"].get("value")
            pv = payload.get(key)
            if target_any is not None:
                pv_list = pv if isinstance(pv, list) else [pv]
                if not any(v in pv_list for v in target_any):
                    return False
            elif target_value is not None:
                if pv != target_value:
                    return False
        if "range" in cond:
            pv = payload.get(key)
            if pv is None:
                return False
            gte = cond["range"].get("gte")
            lte = cond["range"].get("lte")
            if gte is not None and pv < gte:
                return False
            if lte is not None and pv > lte:
                return False
    return True
