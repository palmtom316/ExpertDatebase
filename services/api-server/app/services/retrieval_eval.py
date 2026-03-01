"""Offline retrieval evaluation helpers (Hit@K, MRR)."""

from __future__ import annotations

from typing import Any, Callable


def _to_int_set(value: Any) -> set[int]:
    if not isinstance(value, list):
        return set()
    out: set[int] = set()
    for item in value:
        try:
            out.add(int(item))
        except Exception:  # noqa: BLE001
            continue
    return out


def _payload_matches_spec(payload: dict[str, Any], spec: dict[str, Any]) -> bool:
    if not isinstance(spec, dict):
        return False
    for key in ("doc_id", "version_id", "doc_name", "chapter_id"):
        expected = str(spec.get(key) or "").strip()
        if expected and str(payload.get(key) or "").strip() != expected:
            return False
    page = spec.get("page")
    if page is not None:
        try:
            page_int = int(page)
        except Exception:  # noqa: BLE001
            return False
        start = int(payload.get("page_start") or 0)
        end = int(payload.get("page_end") or start)
        if not (start <= page_int <= end):
            return False
    return True


def _is_relevant_hit(hit: dict[str, Any], sample: dict[str, Any]) -> bool:
    payload = (hit or {}).get("payload") or {}

    expected_doc_id = str(sample.get("expected_doc_id") or "").strip()
    if expected_doc_id and str(payload.get("doc_id") or "").strip() != expected_doc_id:
        return False

    expected_version_id = str(sample.get("expected_version_id") or "").strip()
    if expected_version_id and str(payload.get("version_id") or "").strip() != expected_version_id:
        return False

    expected_doc_name = str(sample.get("expected_doc_name") or "").strip()
    if expected_doc_name and str(payload.get("doc_name") or "").strip() != expected_doc_name:
        return False

    expected_pages = _to_int_set(sample.get("expected_pages"))
    if expected_pages:
        start = int(payload.get("page_start") or 0)
        end = int(payload.get("page_end") or start)
        page_hit = any(start <= page <= end for page in expected_pages)
        if not page_hit:
            return False

    relevant_any = sample.get("relevant_any")
    if isinstance(relevant_any, list) and relevant_any:
        return any(_payload_matches_spec(payload, spec) for spec in relevant_any if isinstance(spec, dict))

    # If no explicit relevance condition provided, treat as non-relevant to avoid false positives.
    return bool(expected_doc_id or expected_version_id or expected_doc_name or expected_pages)


def _first_relevant_rank(hits: list[dict[str, Any]], sample: dict[str, Any]) -> int | None:
    for idx, hit in enumerate(hits, start=1):
        if _is_relevant_hit(hit, sample):
            return idx
    return None


def evaluate_retrieval_samples(
    samples: list[dict[str, Any]],
    search_fn: Callable[[dict[str, Any]], list[dict[str, Any]]],
    top_k: int = 10,
) -> dict[str, Any]:
    if not samples:
        return {
            "query_count": 0,
            "hit_at_5": 0.0,
            "hit_at_10": 0.0,
            "mrr": 0.0,
            "details": [],
        }

    top_k = max(1, int(top_k))
    details: list[dict[str, Any]] = []
    hit5 = 0
    hit10 = 0
    rr_sum = 0.0

    for sample in samples:
        hits = search_fn(sample)
        rank = _first_relevant_rank(hits[:top_k], sample)
        if rank is not None and rank <= 5:
            hit5 += 1
        if rank is not None and rank <= 10:
            hit10 += 1
        if rank is not None:
            rr_sum += 1.0 / rank

        details.append(
            {
                "query": str(sample.get("query") or ""),
                "rank": rank,
                "top_hit": ((hits or [{}])[0].get("payload") or {}) if hits else {},
            }
        )

    count = len(samples)
    return {
        "query_count": count,
        "hit_at_5": hit5 / count,
        "hit_at_10": hit10 / count,
        "mrr": rr_sum / count,
        "details": details,
    }
