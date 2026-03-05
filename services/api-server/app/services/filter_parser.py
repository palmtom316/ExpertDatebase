"""Parse question into Qdrant payload filter spec."""

from __future__ import annotations

import os
import re
from typing import Any

ROLE_KEYWORDS = ["项目经理", "技术负责人", "总工", "安全员", "质量员"]
_CLAUSE_PAT = re.compile(r"(?<!\d)(\d{1,2}(?:\.\d+){1,4}(?:\([0-9A-Za-z]+\))?)(?!\d)")
_STANDARD_PAT = re.compile(
    r"(?<![A-Za-z0-9])((?:GB|DL/T|DL|NB/T|IEC|ISO)\s*[-A-Z]*\s*\d{2,6}(?:-\d{4})?)(?![A-Za-z0-9])",
    flags=re.IGNORECASE,
)
_CERT_PAT = re.compile(r"(?<![A-Z0-9])([A-Z]{1,6}(?:-[A-Z0-9]{1,10}){2,})(?![A-Z0-9])")
_MANDATORY_HINT = re.compile(r"(强制性条文|强制条文|必须执行|一票否决|不得|必须)")


_RANGE_GTE_PAT = re.compile(r"(不低于|不少于|至少|大于等于|>=|≥)")
_RANGE_LTE_PAT = re.compile(r"(不高于|不超过|至多|小于等于|<=|≤)")
_RANGE_GT_PAT = re.compile(r"(高于|大于|>)")
_RANGE_LT_PAT = re.compile(r"(低于|小于|<)")
_EQUAL_PAT = re.compile(r"(等于|为)")


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        token = str(item or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _expand_standard_variants(standards: list[str]) -> list[str]:
    out: list[str] = []
    for item in standards:
        raw = str(item or "").strip().upper()
        if not raw:
            continue
        compact = re.sub(r"\s+", "", raw)
        out.append(raw)
        if compact and compact != raw:
            out.append(compact)
    return _dedupe(out)


def parse_amount_to_wan(text: str) -> float | None:
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(亿|万|万元)", text)
    if not m:
        return None
    value = float(m.group(1))
    unit = m.group(2)
    if unit == "亿":
        return value * 10000
    return value


def extract_clause_ids(text: str) -> list[str]:
    q = str(text or "").strip()
    return _dedupe([m.group(1) for m in _CLAUSE_PAT.finditer(q)])


def parse_filter_spec(question: str, entity_index: Any) -> tuple[dict[str, Any] | None, str, str]:
    q = str(question or "").strip()
    must: list[dict[str, Any]] = []
    sparse_tokens: list[str] = []

    def _numeric_range_from_window(window: str, value: float) -> dict[str, float]:
        if _RANGE_GTE_PAT.search(window):
            return {"gte": value}
        if _RANGE_LTE_PAT.search(window):
            return {"lte": value}
        if _RANGE_GT_PAT.search(window):
            return {"gt": value}
        if _RANGE_LT_PAT.search(window):
            return {"lt": value}
        if _EQUAL_PAT.search(window):
            return {"gte": value, "lte": value}
        return {"gte": value}

    kv_match = re.search(r"(\d{2,3})\s*(kV|KV|千伏)", q)
    if kv_match:
        kv_value = int(kv_match.group(1))
        kv_token = f"{kv_value}kV"
        left = max(0, kv_match.start() - 8)
        right = min(len(q), kv_match.end() + 8)
        window = q[left:right]
        must.append({"key": "val_voltage_kv", "range": _numeric_range_from_window(window, float(kv_value))})
        sparse_tokens.append(kv_token)

    amount_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(亿|万|万元)", q)
    amount_w = parse_amount_to_wan(q)
    if amount_w is not None:
        window = q
        if amount_match:
            left = max(0, amount_match.start() - 8)
            right = min(len(q), amount_match.end() + 8)
            window = q[left:right]
        must.append({"key": "val_contract_amount_w", "range": _numeric_range_from_window(window, amount_w)})
        sparse_tokens.append(str(amount_w))

    role_hit = next((r for r in ROLE_KEYWORDS if r in q), None)

    for name in entity_index.match_names("person", q):
        pid = entity_index.get_id("person", name)
        if not pid:
            continue
        must.append({"key": "entity_person_ids", "match": {"any": [pid]}})
        sparse_tokens.append(name)
        if role_hit:
            must.append({"key": "rel_person_role", "match": {"any": [f"{pid}|{role_hit}"]}})
            sparse_tokens.append(role_hit)

    clause_hits = extract_clause_ids(q)
    if clause_hits:
        # Use ANY semantics for multi-clause queries to avoid impossible AND match.
        must.append({"key": "clause_no", "match": {"any": clause_hits}})
    sparse_tokens.extend(clause_hits)

    if _MANDATORY_HINT.search(q):
        must.append({"key": "is_mandatory", "match": {"value": True}})
        sparse_tokens.append("强制性条文")

    standard_hits = _dedupe([m.group(1).strip().upper() for m in _STANDARD_PAT.finditer(q)])
    standard_values = _expand_standard_variants(standard_hits)
    strict_standard = str(os.getenv("ENABLE_STANDARD_STRICT_FILTER", "1")).strip().lower() in {"1", "true", "yes"}
    if strict_standard and standard_values:
        # Multi-standard query should use ANY semantics to avoid impossible AND constraints.
        must.append({"key": "standard_no", "match": {"any": standard_values}})
    sparse_tokens.extend(standard_hits)

    cert_hits = _dedupe([m.group(1).strip().upper() for m in _CERT_PAT.finditer(q)])
    for cert in cert_hits:
        must.append({"key": "certificate_no", "match": {"value": cert}})
    sparse_tokens.extend(cert_hits)

    filter_json = {"must": must} if must else None
    sparse_query = " ".join(_dedupe([q] + sparse_tokens)).strip()
    dense_query_text = q
    return filter_json, sparse_query, dense_query_text
