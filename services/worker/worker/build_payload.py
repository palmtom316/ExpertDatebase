"""Build Qdrant payload for hybrid retrieval."""

from __future__ import annotations

import re
from typing import Any


def unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            output.append(item)
    return output


def make_excerpt(text: str, limit: int = 200) -> str:
    return text.strip().replace("\n", " ")[:limit]


def collect_person_names(ie_assets: list[dict[str, Any]], relations_light: list[dict[str, Any]], text: str) -> list[str]:
    names = [r.get("source_name") for r in relations_light if r.get("type") == "PERSON_TO_PROJECT"]
    names += re.findall(r"([\u4e00-\u9fa5]{2,4})(?:任|担任)(?:项目经理|技术负责人|总工|安全员|质量员)", text)
    return unique([n for n in names if n])


def collect_project_names(ie_assets: list[dict[str, Any]], relations_light: list[dict[str, Any]], text: str) -> list[str]:
    names = [r.get("target_name") for r in relations_light if r.get("type") == "PERSON_TO_PROJECT"]
    return unique([n for n in names if n])


def collect_equipment_names(ie_assets: list[dict[str, Any]], relations_light: list[dict[str, Any]], text: str) -> list[str]:
    return []


def infer_voltage_kv(ie_assets: list[dict[str, Any]], text: str) -> int | None:
    for a in ie_assets:
        v = (a.get("data_json") or {}).get("voltage_level_kv")
        if v is not None:
            return int(v)
    m = re.search(r"(\d{2,3})\s*(?:kV|KV|千伏)", text)
    return int(m.group(1)) if m else None


def infer_amount_wan(ie_assets: list[dict[str, Any]], text: str) -> float | None:
    for a in ie_assets:
        rmb = (a.get("data_json") or {}).get("contract_amount_rmb")
        if rmb is not None:
            return float(rmb) / 10000.0

    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(亿|万|万元)", text)
    if not m:
        return None
    v = float(m.group(1))
    unit = m.group(2)
    if unit == "亿":
        return v * 10000
    return v


def infer_line_km(ie_assets: list[dict[str, Any]], text: str) -> float | None:
    for a in ie_assets:
        value = (a.get("data_json") or {}).get("line_length_km")
        if value is not None:
            return float(value)
    return None


def infer_capacity_mva(ie_assets: list[dict[str, Any]], text: str) -> float | None:
    for a in ie_assets:
        data = a.get("data_json") or {}
        value = data.get("substation_capacity_mva") or data.get("transformer_capacity_mva")
        if value is not None:
            return float(value)
    return None


def build_payload(
    chunk: dict[str, Any],
    ie_assets: list[dict[str, Any]],
    relations_light: list[dict[str, Any]],
    entity_index: Any,
    page_type: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "doc_id": chunk["doc_id"],
        "version_id": chunk.get("version_id", ""),
        "doc_name": chunk.get("doc_name", ""),
        "chunk_id": chunk["chunk_id"],
        "chapter_id": chunk["chapter_id"],
        "page_start": chunk["page_start"],
        "page_end": chunk["page_end"],
        "doc_type": chunk.get("doc_type", "unknown"),
        "page_type": page_type or "other",
        "has_citation": True,
        "excerpt": make_excerpt(chunk.get("text", "")),
        "chunk_text": chunk.get("text", ""),
        "block_ids": chunk.get("block_ids", []),
    }

    person_names = collect_person_names(ie_assets, relations_light, chunk.get("text", ""))
    project_names = collect_project_names(ie_assets, relations_light, chunk.get("text", ""))
    equip_names = collect_equipment_names(ie_assets, relations_light, chunk.get("text", ""))

    payload["entity_person_names"] = person_names
    payload["entity_project_names"] = project_names
    payload["entity_equipment_names"] = equip_names

    payload["entity_person_ids"] = [entity_index.get_or_create_id("person", n) for n in person_names]
    payload["entity_project_ids"] = [entity_index.get_or_create_id("project", n) for n in project_names]
    payload["entity_equipment_ids"] = [entity_index.get_or_create_id("equipment", n) for n in equip_names]

    rel_person_role: list[str] = []
    rel_person_project: list[str] = []
    rel_person_role_project: list[str] = []

    for rel in relations_light:
        if rel.get("type") != "PERSON_TO_PROJECT":
            continue
        pid = entity_index.get_or_create_id("person", rel.get("source_name", ""))
        prj = entity_index.get_or_create_id("project", rel.get("target_name", ""))
        role = (rel.get("properties") or {}).get("role_in_project")

        rel_person_project.append(f"{pid}|{prj}")
        if role:
            rel_person_role.append(f"{pid}|{role}")
            rel_person_role_project.append(f"{pid}|{role}|{prj}")

    payload["rel_person_role"] = unique(rel_person_role)
    payload["rel_person_project"] = unique(rel_person_project)
    payload["rel_person_role_project"] = unique(rel_person_role_project)

    payload["val_voltage_kv"] = infer_voltage_kv(ie_assets, chunk.get("text", ""))
    payload["val_contract_amount_w"] = infer_amount_wan(ie_assets, chunk.get("text", ""))
    payload["val_line_length_km"] = infer_line_km(ie_assets, chunk.get("text", ""))
    payload["val_capacity_mva"] = infer_capacity_mva(ie_assets, chunk.get("text", ""))

    return payload
