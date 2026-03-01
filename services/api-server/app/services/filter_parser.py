"""Parse question into Qdrant payload filter spec."""

from __future__ import annotations

import re
from typing import Any

ROLE_KEYWORDS = ["项目经理", "技术负责人", "总工", "安全员", "质量员"]
_CLAUSE_PAT = re.compile(r"(?<!\d)(\d{1,2}(?:\.\d+){1,4})(?!\d)")
_STANDARD_PAT = re.compile(
    r"(?<![A-Za-z0-9])((?:GB|DL/T|DL|NB/T|IEC|ISO)\s*[-A-Z]*\s*\d{2,6}(?:-\d{4})?)(?![A-Za-z0-9])",
    flags=re.IGNORECASE,
)
_CERT_PAT = re.compile(r"(?<![A-Z0-9])([A-Z]{1,6}(?:-[A-Z0-9]{1,10}){2,})(?![A-Z0-9])")


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


def parse_amount_to_wan(text: str) -> float | None:
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(亿|万|万元)", text)
    if not m:
        return None
    value = float(m.group(1))
    unit = m.group(2)
    if unit == "亿":
        return value * 10000
    return value


def parse_filter_spec(question: str, entity_index: Any) -> tuple[dict[str, Any] | None, str, str]:
    q = str(question or "").strip()
    must: list[dict[str, Any]] = []
    sparse_tokens: list[str] = []

    kv_match = re.search(r"(\d{2,3})\s*(kV|KV|千伏)", q)
    if kv_match:
        kv_token = f"{kv_match.group(1)}kV"
        must.append({"key": "val_voltage_kv", "range": {"gte": int(kv_match.group(1))}})
        sparse_tokens.append(kv_token)

    amount_w = parse_amount_to_wan(q)
    if amount_w is not None:
        must.append({"key": "val_contract_amount_w", "range": {"gte": amount_w}})
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

    clause_hits = _dedupe([m.group(1) for m in _CLAUSE_PAT.finditer(q)])
    for clause in clause_hits:
        must.append({"key": "clause_no", "match": {"value": clause}})
    sparse_tokens.extend(clause_hits)

    standard_hits = _dedupe([m.group(1).strip().upper() for m in _STANDARD_PAT.finditer(q)])
    for standard in standard_hits:
        must.append({"key": "standard_no", "match": {"value": standard}})
    sparse_tokens.extend(standard_hits)

    cert_hits = _dedupe([m.group(1).strip().upper() for m in _CERT_PAT.finditer(q)])
    for cert in cert_hits:
        must.append({"key": "certificate_no", "match": {"value": cert}})
    sparse_tokens.extend(cert_hits)

    filter_json = {"must": must} if must else None
    sparse_query = " ".join(_dedupe([q] + sparse_tokens)).strip()
    dense_query_text = q
    return filter_json, sparse_query, dense_query_text
