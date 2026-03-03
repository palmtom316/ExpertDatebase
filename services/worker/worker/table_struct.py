"""Table struct extraction for key table types."""

from __future__ import annotations

import os
from typing import Any


def _normalize_lines(raw_text: str) -> list[str]:
    return [x.strip() for x in str(raw_text or "").splitlines() if x.strip()]


def _split_row(line: str) -> list[str]:
    if "|" in line:
        return [x.strip() for x in line.split("|") if x.strip()]
    if "\t" in line:
        return [x.strip() for x in line.split("\t") if x.strip()]
    return [x.strip() for x in line.split() if x.strip()]


def _is_power_table(text: str) -> bool:
    return any(k in text for k in ["业绩", "电压", "kV", "金额", "线路"])


def _is_device_table(text: str) -> bool:
    return any(k in text for k in ["设备", "型号", "数量", "主变", "断路器"])


def _is_qualification_table(text: str) -> bool:
    return any(k in text for k in ["资格", "证书", "执业", "人员", "建造师"])


def _readable_ratio(text: str) -> float:
    s = str(text or "").strip()
    if not s:
        return 0.0
    keep = 0
    for ch in s:
        if ch.isalnum() or ("\u4e00" <= ch <= "\u9fff"):
            keep += 1
            continue
        if ch in "，。！？；：、（）()[]【】《》“”‘’+-*/%=._:;,\"' \n\t|":
            keep += 1
    return keep / max(1, len(s))


def _needs_vl_fallback(header: list[str], row_items: list[dict[str, Any]], raw_text: str) -> bool:
    if not str(raw_text or "").strip():
        return False
    if not row_items:
        return True

    cell_counts = [len(list(row.get("cells") or [])) for row in row_items]
    if not cell_counts:
        return True

    max_cells = max(cell_counts)
    min_cells = min(cell_counts)
    if max_cells <= 1:
        return True
    if len(header) >= 2 and min_cells == 1 and max_cells >= 3:
        return True

    row_text = "\n".join(" | ".join(str(c or "") for c in (row.get("cells") or [])) for row in row_items)
    return _readable_ratio(row_text) < 0.55


def _rows_from_vl_text(text: str) -> tuple[list[str], list[dict[str, Any]]]:
    lines = _normalize_lines(text)
    if len(lines) < 2:
        return [], []
    header = _split_row(lines[0])
    rows = [_split_row(line) for line in lines[1:]]
    row_items = [{"cells": row} for row in rows if row]
    return header, row_items


def _stub_rows(text: str) -> list[dict[str, Any]]:
    return [{"cells": [str(text or "")[:160]]}]


def extract_table_struct(
    tables: list[dict[str, Any]],
    vl_repairs_by_table_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {
        "power_param_table": [],
        "device_inventory_table": [],
        "qualification_table": [],
    }
    repair_map = vl_repairs_by_table_id or {}
    min_confidence = float(os.getenv("WORKER_TABLE_VL_MIN_CONFIDENCE", "0.45"))

    for table in tables:
        text = str(table.get("raw_text", ""))
        lines = _normalize_lines(text)
        rows = [_split_row(line) for line in lines[1:]] if len(lines) > 1 else []
        row_items = [{"cells": row} for row in rows if row]
        header = _split_row(lines[0]) if lines else []

        repair_strategy = "none"
        if _needs_vl_fallback(header=header, row_items=row_items, raw_text=text):
            repair_item = repair_map.get(str(table.get("table_id") or "").strip()) or {}
            repair_text = str(repair_item.get("recognized_text") or "").strip()
            confidence = float(repair_item.get("confidence") or 0.0)
            vl_header, vl_rows = _rows_from_vl_text(repair_text)
            if vl_rows and confidence >= min_confidence:
                row_items = vl_rows
                if vl_header:
                    header = vl_header
                repair_strategy = "vl_fallback"
            else:
                row_items = _stub_rows(text)
                repair_strategy = "stub"

        item = {
            "table_id": table.get("table_id"),
            "page_no": table.get("page_no"),
            "header": header,
            "rows": row_items,
            "raw_text": text,
            "repair_strategy": repair_strategy,
        }

        if _is_power_table(text):
            out["power_param_table"].append(item)
        if _is_device_table(text):
            out["device_inventory_table"].append(item)
        if _is_qualification_table(text):
            out["qualification_table"].append(item)

    return out
