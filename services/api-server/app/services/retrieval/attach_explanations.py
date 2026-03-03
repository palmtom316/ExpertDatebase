"""Attach clause/explanation sibling hits for paired citation display."""

from __future__ import annotations

from typing import Any, Callable


def attach_explanations(
    hits: list[dict[str, Any]],
    fetch_by_filter_fn: Callable[[dict[str, Any], int], list[dict[str, Any]]],
    top_k_attach: int = 5,
) -> list[dict[str, Any]]:
    out = list(hits)
    seen = {h.get("chunk_id") for h in hits}
    for hit in hits[:top_k_attach]:
        payload = hit.get("payload", {}) or {}
        clause_id = payload.get("clause_id")
        doc_type = payload.get("doc_type")
        if not clause_id or doc_type not in ("clause", "explanation"):
            continue
        target_doc_type = "explanation" if doc_type == "clause" else "clause"
        filter_json = {
            "must": [
                {"key": "clause_id", "match": {"value": clause_id}},
                {"key": "doc_type", "match": {"value": target_doc_type}},
            ]
        }
        siblings = fetch_by_filter_fn(filter_json, 1) or []
        for sibling in siblings:
            sibling_id = sibling.get("chunk_id")
            if sibling_id and sibling_id not in seen:
                out.append(sibling)
                seen.add(sibling_id)
    out.sort(key=lambda item: 0 if (item.get("payload", {}).get("doc_type") == "clause") else 1)
    return out
