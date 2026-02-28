"""Schema-based IE extraction (MVP rule-driven implementation)."""

from __future__ import annotations

import re
from typing import Any


def _find(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, re.MULTILINE)
    if not m:
        return None
    return m.group(1).strip()


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

    excerpt = text.strip().replace("\n", " ")[:220]
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
