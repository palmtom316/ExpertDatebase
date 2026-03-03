"""VL fallback utilities for low-confidence table extraction."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VLFallbackResult:
    table_summary: str
    row_facts: list[dict]
    debug: dict


def should_use_vl(table_confidence: float | None, stitch_ok: bool, is_image_table: bool) -> bool:
    if is_image_table:
        return True
    if table_confidence is not None and table_confidence < 0.5:
        return True
    if not stitch_ok:
        return True
    return False


def call_vl_stub(image_bytes: bytes, prompt: str) -> str:
    raise NotImplementedError("Replace with your VL model API call. Must return JSON array rows.")


def vl_to_threepack(vl_json_rows: list[dict], table_title: str) -> VLFallbackResult:
    lines = [table_title, "（VL 兜底识别）"]
    for row in vl_json_rows[:6]:
        lines.append(str(row))
    return VLFallbackResult(table_summary="\n".join(lines), row_facts=vl_json_rows, debug={"rows": len(vl_json_rows)})
