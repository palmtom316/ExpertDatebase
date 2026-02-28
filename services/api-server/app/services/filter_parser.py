"""Parse question into Qdrant payload filter spec."""

from __future__ import annotations

import re
from typing import Any

ROLE_KEYWORDS = ["项目经理", "技术负责人", "总工", "安全员", "质量员"]


def parse_amount_to_wan(text: str) -> float | None:
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(亿|万|万元)", text)
    if not m:
        return None
    value = float(m.group(1))
    unit = m.group(2)
    if unit == "亿":
        return value * 10000
    return value


def parse_filter_spec(question: str, entity_index: Any) -> tuple[dict[str, Any] | None, str]:
    must: list[dict[str, Any]] = []

    kv_match = re.search(r"(\d{2,3})\s*(kV|KV|千伏)", question)
    if kv_match:
        must.append({"key": "val_voltage_kv", "range": {"gte": int(kv_match.group(1))}})

    amount_w = parse_amount_to_wan(question)
    if amount_w is not None:
        must.append({"key": "val_contract_amount_w", "range": {"gte": amount_w}})

    role_hit = next((r for r in ROLE_KEYWORDS if r in question), None)

    for name in entity_index.match_names("person", question):
        pid = entity_index.get_id("person", name)
        if not pid:
            continue
        must.append({"key": "entity_person_ids", "match": {"any": [pid]}})
        if role_hit:
            must.append({"key": "rel_person_role", "match": {"any": [f"{pid}|{role_hit}"]}})

    filter_json = {"must": must} if must else None
    return filter_json, question
