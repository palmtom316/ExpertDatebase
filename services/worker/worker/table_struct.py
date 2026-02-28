"""Table struct extraction for key table types."""

from __future__ import annotations

from typing import Any


def _normalize_lines(raw_text: str) -> list[str]:
    return [x.strip() for x in str(raw_text or "").splitlines() if x.strip()]


def _split_row(line: str) -> list[str]:
    if "|" in line:
        return [x.strip() for x in line.split("|")]
    if "\t" in line:
        return [x.strip() for x in line.split("\t")]
    return [x.strip() for x in line.split() if x.strip()]


def _is_power_table(text: str) -> bool:
    return any(k in text for k in ["业绩", "电压", "kV", "金额", "线路"])


def _is_device_table(text: str) -> bool:
    return any(k in text for k in ["设备", "型号", "数量", "主变", "断路器"])


def _is_qualification_table(text: str) -> bool:
    return any(k in text for k in ["资格", "证书", "执业", "人员", "建造师"])


def extract_table_struct(tables: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {
        "power_param_table": [],
        "device_inventory_table": [],
        "qualification_table": [],
    }

    for table in tables:
        text = str(table.get("raw_text", ""))
        lines = _normalize_lines(text)
        rows = [_split_row(line) for line in lines[1:]] if len(lines) > 1 else []
        row_items = [{"cells": row} for row in rows if row]
        item = {
            "table_id": table.get("table_id"),
            "page_no": table.get("page_no"),
            "header": _split_row(lines[0]) if lines else [],
            "rows": row_items,
            "raw_text": text,
            "repair_strategy": "none",
        }
        if not item["rows"] and text:
            # LLM repair fallback (offline deterministic placeholder):
            # if parse fails, keep a single-row repaired structure for downstream continuity.
            item["rows"] = [{"cells": [text[:160]]}]
            item["repair_strategy"] = "llm_fallback_stub"

        if _is_power_table(text):
            out["power_param_table"].append(item)
        if _is_device_table(text):
            out["device_inventory_table"].append(item)
        if _is_qualification_table(text):
            out["qualification_table"].append(item)

    return out
