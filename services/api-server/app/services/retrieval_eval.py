"""Offline retrieval evaluation helpers (Hit@K, MRR, and constraint-oriented metrics)."""

from __future__ import annotations

import os
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


def _to_token_set(value: Any) -> set[str]:
    if isinstance(value, str):
        token = value.strip()
        return {token} if token else set()
    if not isinstance(value, list):
        return set()
    out: set[str] = set()
    for item in value:
        token = str(item or "").strip()
        if token:
            out.add(token)
    return out


def _payload_matches_spec(payload: dict[str, Any], spec: dict[str, Any]) -> bool:
    if not isinstance(spec, dict):
        return False
    for key in ("doc_id", "version_id", "doc_name", "chapter_id", "clause_id", "clause_no", "article_no", "constraint_type"):
        expected = str(spec.get(key) or "").strip()
        if expected and str(payload.get(key) or "").strip() != expected:
            return False
    if "is_mandatory" in spec:
        if bool(payload.get("is_mandatory")) != bool(spec.get("is_mandatory")):
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


def _has_complete_citation(payload: dict[str, Any]) -> bool:
    has_doc = bool(str(payload.get("doc_name") or payload.get("doc_id") or "").strip())
    has_page = payload.get("page_start") is not None
    has_excerpt = bool(str(payload.get("excerpt") or payload.get("chunk_text") or "").strip())
    return has_doc and has_page and has_excerpt


def _sample_expected_clause_ids(sample: dict[str, Any]) -> set[str]:
    expected = _to_token_set(sample.get("expected_clause_ids"))
    expected_single = str(sample.get("expected_clause_id") or "").strip()
    if expected_single:
        expected.add(expected_single)
    return expected


def _sample_clause_hit(hits: list[dict[str, Any]], sample: dict[str, Any], top_k: int) -> bool | None:
    expected_clause_ids = _sample_expected_clause_ids(sample)
    if expected_clause_ids:
        for hit in hits[:top_k]:
            payload = (hit or {}).get("payload") or {}
            clause_candidates = {
                str(payload.get("clause_id") or "").strip(),
                str(payload.get("clause_no") or "").strip(),
                str(payload.get("article_no") or "").strip(),
            }
            if expected_clause_ids.intersection({c for c in clause_candidates if c}):
                return True
        return False

    relevant_any = sample.get("relevant_any")
    if isinstance(relevant_any, list):
        clause_specs = [
            spec
            for spec in relevant_any
            if isinstance(spec, dict) and any(str(spec.get(k) or "").strip() for k in ("clause_id", "clause_no", "article_no"))
        ]
        if clause_specs:
            return any(
                _payload_matches_spec((hit or {}).get("payload") or {}, spec)
                for hit in hits[:top_k]
                for spec in clause_specs
            )
    return None


def _sample_constraint_specs(sample: dict[str, Any]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    raw_specs = sample.get("constraint_specs")
    if isinstance(raw_specs, list):
        specs.extend([spec for spec in raw_specs if isinstance(spec, dict)])

    expected_clause_ids = _sample_expected_clause_ids(sample)
    expected_is_mandatory = sample.get("expected_is_mandatory")
    expected_constraint_type = str(sample.get("expected_constraint_type") or "").strip()

    if expected_clause_ids and (expected_is_mandatory is not None or expected_constraint_type):
        for clause_id in expected_clause_ids:
            spec: dict[str, Any] = {"clause_id": clause_id}
            if expected_is_mandatory is not None:
                spec["is_mandatory"] = bool(expected_is_mandatory)
            if expected_constraint_type:
                spec["constraint_type"] = expected_constraint_type
            specs.append(spec)

    return specs


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
            "evidence_hit_rate_at_10": 0.0,
            "mrr": 0.0,
            "clause_hit_at_k": 0.0,
            "constraint_coverage": 0.0,
            "citation_completeness": 0.0,
            "details": [],
            "failed_samples": [],
            "release_gate": {"passed": False, "reason": "empty dataset"},
        }

    top_k = max(1, int(top_k))
    details: list[dict[str, Any]] = []
    hit5 = 0
    hit10 = 0
    rr_sum = 0.0
    evidence_hit10 = 0
    failed_samples: list[dict[str, Any]] = []

    clause_eligible = 0
    clause_hits = 0
    constraint_specs_total = 0
    constraint_specs_hit = 0
    total_relevant_hits = 0
    complete_relevant_citations = 0

    for sample in samples:
        hits = search_fn(sample)
        hits_top_k = hits[:top_k]
        rank = _first_relevant_rank(hits_top_k, sample)
        if rank is not None and rank <= 5:
            hit5 += 1
        if rank is not None and rank <= 10:
            hit10 += 1
            evidence_hit10 += 1
        if rank is not None:
            rr_sum += 1.0 / rank
        else:
            failed_samples.append({"query": str(sample.get("query") or ""), "expected": sample})

        clause_hit = _sample_clause_hit(hits, sample, top_k)
        if clause_hit is not None:
            clause_eligible += 1
            if clause_hit:
                clause_hits += 1

        constraint_specs = _sample_constraint_specs(sample)
        if constraint_specs:
            constraint_specs_total += len(constraint_specs)
            for spec in constraint_specs:
                if any(_payload_matches_spec((hit or {}).get("payload") or {}, spec) for hit in hits_top_k):
                    constraint_specs_hit += 1

        relevant_hits = [hit for hit in hits_top_k if _is_relevant_hit(hit, sample)]
        total_relevant_hits += len(relevant_hits)
        complete_relevant_citations += sum(
            1 for hit in relevant_hits if _has_complete_citation((hit or {}).get("payload") or {})
        )

        details.append(
            {
                "query": str(sample.get("query") or ""),
                "rank": rank,
                "top_hit": ((hits or [{}])[0].get("payload") or {}) if hits else {},
            }
        )

    count = len(samples)
    hit_at_10 = hit10 / count
    mrr = rr_sum / count
    evidence_hit_rate_at_10 = evidence_hit10 / count
    clause_hit_at_k = (clause_hits / clause_eligible) if clause_eligible else 0.0
    constraint_coverage = (constraint_specs_hit / constraint_specs_total) if constraint_specs_total else 0.0
    citation_completeness = (
        complete_relevant_citations / total_relevant_hits if total_relevant_hits else 0.0
    )

    min_queries = max(1, int(os.getenv("EVAL_MIN_QUERIES", "30")))
    min_hit10 = float(os.getenv("EVAL_MIN_HIT10", "0.75"))
    min_mrr = float(os.getenv("EVAL_MIN_MRR", "0.45"))
    min_evidence = float(os.getenv("EVAL_MIN_EVIDENCE_HIT10", "0.80"))
    min_clause_hit = float(os.getenv("EVAL_MIN_CLAUSE_HIT_AT_K", "0.70"))
    min_constraint_coverage = float(os.getenv("EVAL_MIN_CONSTRAINT_COVERAGE", "0.70"))
    min_citation_completeness = float(os.getenv("EVAL_MIN_CITATION_COMPLETENESS", "0.85"))

    gate_passed = (
        count >= min_queries
        and hit_at_10 >= min_hit10
        and mrr >= min_mrr
        and evidence_hit_rate_at_10 >= min_evidence
        and (clause_eligible == 0 or clause_hit_at_k >= min_clause_hit)
        and (constraint_specs_total == 0 or constraint_coverage >= min_constraint_coverage)
        and (total_relevant_hits == 0 or citation_completeness >= min_citation_completeness)
    )
    gate_reason = "ok" if gate_passed else "metrics or sample count below threshold"
    return {
        "query_count": count,
        "hit_at_5": hit5 / count,
        "hit_at_10": hit_at_10,
        "evidence_hit_rate_at_10": evidence_hit_rate_at_10,
        "mrr": mrr,
        "clause_hit_at_k": clause_hit_at_k,
        "constraint_coverage": constraint_coverage,
        "citation_completeness": citation_completeness,
        "details": details,
        "failed_samples": failed_samples,
        "release_gate": {
            "passed": gate_passed,
            "reason": gate_reason,
            "thresholds": {
                "min_queries": min_queries,
                "min_hit_at_10": min_hit10,
                "min_mrr": min_mrr,
                "min_evidence_hit_rate_at_10": min_evidence,
                "min_clause_hit_at_k": min_clause_hit,
                "min_constraint_coverage": min_constraint_coverage,
                "min_citation_completeness": min_citation_completeness,
            },
        },
    }
