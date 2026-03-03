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
    s = str(text or "")
    # Strip OCR artifacts that pollute retrieval snippets.
    s = re.sub(r"table\s+images/\S+", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]


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


def infer_clause_no(text: str) -> str | None:
    m = re.search(r"(?<!\d)(\d{1,2}(?:\.\d+){1,4}(?:\([0-9A-Za-z]+\))?)(?!\d)", str(text or ""))
    return m.group(1) if m else None


def infer_standard_no(ie_assets: list[dict[str, Any]], text: str) -> str | None:
    for a in ie_assets:
        name = (a.get("data_json") or {}).get("standard_name")
        if name:
            return str(name).strip().upper()
    m = re.search(
        r"(?<![A-Za-z0-9])((?:GB|DL/T|DL|NB/T|IEC|ISO)\s*[-A-Z]*\s*\d{2,6}(?:-\d{4})?)(?![A-Za-z0-9])",
        str(text or ""),
        flags=re.IGNORECASE,
    )
    return m.group(1).upper().strip() if m else None


def infer_certificate_no(ie_assets: list[dict[str, Any]], text: str) -> str | None:
    for a in ie_assets:
        cert = (a.get("data_json") or {}).get("certificate")
        if cert:
            return str(cert).strip().upper()
    m = re.search(r"(?<![A-Z0-9])([A-Z]{1,6}(?:-[A-Z0-9]{1,10}){2,})(?![A-Z0-9])", str(text or ""))
    return m.group(1).upper().strip() if m else None


def infer_is_mandatory(ie_assets: list[dict[str, Any]], text: str) -> bool:
    for asset in ie_assets:
        value = (asset.get("data_json") or {}).get("is_mandatory")
        if isinstance(value, bool):
            return value
    raw = str(text or "")
    return bool(re.search(r"(强制性条文|必须|不得|严禁|应当)", raw))


def infer_article_path(clause_id: str) -> list[str]:
    raw = str(clause_id or "").strip()
    if not raw:
        return []
    plain = re.sub(r"\([0-9A-Za-z]+\)$", "", raw)
    parts = [p for p in plain.split(".") if p]
    if not parts:
        return []
    out: list[str] = []
    for idx in range(1, len(parts) + 1):
        out.append(".".join(parts[:idx]))
    return out


def infer_constraint_type(text: str, is_mandatory: bool) -> str:
    raw = str(text or "")
    if is_mandatory or re.search(r"(强制性条文|不得|严禁|禁止)", raw):
        return "mandatory"
    if re.search(r"(应|应当|宜)", raw):
        return "recommended"
    return "informative"


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
        "source_type": chunk.get("source_type", "text"),
        "table_id": chunk.get("table_id"),
        "row_index": chunk.get("row_index"),
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
    clause_id = str(chunk.get("clause_id") or "").strip() or infer_clause_no(chunk.get("text", ""))
    payload["clause_id"] = clause_id
    payload["clause_no"] = clause_id
    payload["is_mandatory"] = infer_is_mandatory(ie_assets, chunk.get("text", ""))
    payload["standard_no"] = infer_standard_no(ie_assets, chunk.get("text", ""))
    payload["certificate_no"] = infer_certificate_no(ie_assets, chunk.get("text", ""))

    article_path = infer_article_path(clause_id)
    payload["article_path"] = article_path
    payload["chapter_no"] = article_path[0] if len(article_path) >= 1 else ""
    payload["section_no"] = article_path[1] if len(article_path) >= 2 else ""
    payload["article_no"] = clause_id
    payload["constraint_type"] = infer_constraint_type(
        text=chunk.get("text", ""),
        is_mandatory=bool(payload["is_mandatory"]),
    )

    return payload
