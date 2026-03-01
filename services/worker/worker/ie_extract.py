"""Schema-based IE extraction (MVP rule-driven implementation)."""

from __future__ import annotations

import re
from typing import Any


def _find(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, re.MULTILINE)
    if not m:
        return None
    return m.group(1).strip()


def _normalize_line(line: str) -> str:
    text = str(line or "")
    text = text.replace("\x00", " ")
    text = re.sub(r"\$[^$]{0,200}\$", " ", text)
    text = re.sub(r"\\[a-zA-Z]+\s*\{[^}]*\}", " ", text)
    text = re.sub(r"\\[a-zA-Z]+", " ", text)
    text = text.replace("{", " ").replace("}", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _looks_like_toc_line(line: str) -> bool:
    text = str(line or "").strip()
    if not text:
        return True
    lower = text.lower()
    if re.search(r"\b\d{1,2}\.\d{1,2}(?:\.\d+)?\s*[a-z]", lower) and re.search(r"\(\s*\d{1,3}\s*\)", lower):
        return True
    if re.search(r"[.…]{2,}\s*\(?\d{1,3}\)?\s*$", text):
        return True
    if "table of content" in lower or "contents" == lower:
        return True
    return False


def _readable_ratio(text: str) -> float:
    s = str(text or "")
    if not s:
        return 0.0
    readable = 0
    for ch in s:
        if ch.isalnum():
            readable += 1
            continue
        if "\u4e00" <= ch <= "\u9fff":
            readable += 1
            continue
        if ch in "，。！？；：、（）()[]【】《》“”‘’+-*/%=._:;,\"' ":
            readable += 1
    return readable / max(1, len(s))


def _build_readable_excerpt(text: str, limit: int = 220) -> str:
    raw_lines = [x for x in str(text or "").splitlines() if str(x or "").strip()]
    cleaned_lines = [_normalize_line(line) for line in raw_lines]
    cleaned_lines = [line for line in cleaned_lines if line and not _looks_like_toc_line(line)]

    keywords = [
        "项目名称",
        "工程名称",
        "业主单位",
        "建设单位",
        "合同金额",
        "中标价",
        "项目经理",
        "技术负责人",
        "资格证",
        "证书",
        "设备",
        "断路器",
        "标准",
        "条款",
    ]
    strong = [line for line in cleaned_lines if any(k in line for k in keywords)]
    pool = strong or cleaned_lines

    selected: list[str] = []
    for line in pool:
        if _readable_ratio(line) < 0.6:
            continue
        if len(line) < 4:
            continue
        selected.append(line)
        joined = "；".join(selected)
        if len(joined) >= limit:
            break

    if not selected:
        fallback = _normalize_line(str(text or ""))
        if _readable_ratio(fallback) < 0.55:
            return ""
        return fallback[:limit]

    return "；".join(selected)[:limit]


def _parse_amount_rmb(text: str) -> tuple[str | None, float | None]:
    raw = _find(r"(?:合同金额|合同价|中标价)[:：\s]*([0-9,.]+\s*(?:亿元|万元|万|元)?)", text)
    if not raw:
        return None, None
    m = re.search(r"([0-9,.]+)\s*(亿元|万元|万|元)?", raw)
    if not m:
        return raw, None
    value = float(m.group(1).replace(",", ""))
    unit = m.group(2) or "元"
    if unit == "亿元":
        return raw, value * 100000000
    if unit in {"万元", "万"}:
        return raw, value * 10000
    return raw, value


def _parse_voltage_kv(text: str) -> int | None:
    m = re.search(r"(\d{2,3})\s*(?:kV|KV|千伏)", text)
    if not m:
        return None
    return int(m.group(1))


def _find_person_name(text: str) -> str | None:
    direct = _find(r"(?:项目经理|技术负责人|总工|安全员|质量员)[:：\s]*([\u4e00-\u9fa5]{2,4})", text)
    if direct:
        return direct
    rel = re.search(r"([\u4e00-\u9fa5]{2,4})(?:任|担任)(?:项目经理|技术负责人|总工|安全员|质量员)", text)
    return rel.group(1) if rel else None


def _find_role(text: str) -> str | None:
    m = re.search(r"(项目经理|技术负责人|总工|安全员|质量员)", text)
    if not m:
        return None
    return m.group(1)


def _find_qualification(text: str) -> str | None:
    return _find(r"(?:资格证书|执业资格|证书)[:：\s]*([^\n]+)", text)


def _find_equipment(text: str) -> str | None:
    return _find(r"(?:主要设备|设备名称|设备)[:：\s]*([^\n]+)", text)


def _find_standard(text: str) -> str | None:
    return _find(r"(?:执行标准|标准编号|标准)[:：\s]*([^\n]+)", text)


def extract_assets_from_chapter(text: str, page_no: int) -> list[dict[str, Any]]:
    project_name = _find(r"(?:项目名称|工程名称)[:：\s]*([^\n]+)", text)
    owner_unit = _find(r"(?:业主单位|建设单位|发包人)[:：\s]*([^\n]+)", text)
    sign_date = _find(r"(?:签订日期|合同签订|签约日期)[:：\s]*([0-9]{4}[-/.年][0-9]{1,2}[-/.月][0-9]{1,2})", text)
    amount_original, amount_rmb = _parse_amount_rmb(text)
    voltage_kv = _parse_voltage_kv(text)
    person_name = _find_person_name(text)
    role_name = _find_role(text)
    qualification = _find_qualification(text)
    equipment = _find_equipment(text)
    standard_name = _find_standard(text)

    if not any(
        [
            project_name,
            owner_unit,
            sign_date,
            amount_original,
            voltage_kv,
            person_name,
            qualification,
            equipment,
            standard_name,
        ]
    ):
        return []

    excerpt = _build_readable_excerpt(text, limit=220)
    assets: list[dict[str, Any]] = []

    assets.append(
        {
            "asset_type": "project",
            "data_json": {
                "project_name": project_name,
                "owner_unit": owner_unit,
                "contract_sign_date": sign_date,
                "contract_amount_original": amount_original,
                "contract_amount_rmb": amount_rmb,
                "voltage_level_kv": voltage_kv,
                "substation_capacity_mva": None,
                "line_length_km": None,
                "transformer_capacity_mva": None,
                "cable_type": None,
            },
            "source_page": page_no,
            "source_excerpt": excerpt,
            "source_type": "chapter_text",
            "block_id": None,
            "table_id": None,
            "row_index": None,
        }
    )

    if person_name:
        assets.append(
            {
                "asset_type": "person",
                "data_json": {
                    "name": person_name,
                    "role": role_name,
                    "project_name": project_name,
                },
                "source_page": page_no,
                "source_excerpt": excerpt,
                "source_type": "chapter_text",
                "block_id": None,
                "table_id": None,
                "row_index": None,
            }
        )

    if qualification:
        assets.append(
            {
                "asset_type": "qualification",
                "data_json": {
                    "person_name": person_name,
                    "certificate": qualification,
                },
                "source_page": page_no,
                "source_excerpt": excerpt,
                "source_type": "chapter_text",
                "block_id": None,
                "table_id": None,
                "row_index": None,
            }
        )

    if equipment:
        assets.append(
            {
                "asset_type": "equipment",
                "data_json": {
                    "name": equipment,
                    "project_name": project_name,
                },
                "source_page": page_no,
                "source_excerpt": excerpt,
                "source_type": "chapter_text",
                "block_id": None,
                "table_id": None,
                "row_index": None,
            }
        )

    if standard_name:
        assets.append(
            {
                "asset_type": "standard",
                "data_json": {
                    "standard_name": standard_name,
                },
                "source_page": page_no,
                "source_excerpt": excerpt,
                "source_type": "chapter_text",
                "block_id": None,
                "table_id": None,
                "row_index": None,
            }
        )

    return assets
