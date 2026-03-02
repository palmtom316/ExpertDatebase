"""Normalize MinerU output into block/table intermediate format."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any


def _is_toc_like(text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return True
    lower = s.lower()
    if "contents" in lower or "table of contents" in lower:
        return True
    # Typical TOC pattern: multiple section markers + multiple page numbers.
    section_markers = len(re.findall(r"\d+\.\d+(?:\.\d+)?", s))
    page_refs = len(re.findall(r"[\(\（]\s*\d{1,3}\s*[\)\）]", s))
    if section_markers >= 2 and page_refs >= 2:
        return True
    # Single TOC line like "3 基本规定 (5)".
    if page_refs >= 1 and len(s) <= 100 and re.search(r"^\d+(?:\s|[.、])", s):
        return True
    if re.search(r"[.…]{2,}\s*[\(\（]?\s*\d{1,3}\s*[\)\）]?\s*$", s):
        return True
    return False


def _clean_block_text(text: str) -> str:
    s = str(text or "")
    s = "".join(ch for ch in s if ch in ("\n", "\t") or ord(ch) >= 32)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _clean_table_text(text: str) -> str:
    s = str(text or "")
    s = "".join(ch for ch in s if ch in ("\n", "\t") or ord(ch) >= 32)
    lines = [re.sub(r"\s+", " ", line).strip() for line in s.splitlines() if line.strip()]
    return "\n".join(lines).strip()


def _strip_continuation_marker(line: str) -> str:
    s = str(line or "").strip()
    return re.sub(r"^(续表(?:\s*\d+)?|continued(?:\s*table)?|cont\.)\s*[:：\-]?\s*", "", s, flags=re.IGNORECASE).strip()


def _looks_cross_page_table(text: str) -> bool:
    s = str(text or "").strip().lower()
    if not s:
        return False
    return any(mark in s for mark in ["续表", "continued", "cont."])


def _table_header(raw_text: str) -> str:
    lines = [line.strip() for line in str(raw_text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    return _strip_continuation_marker(lines[0]).lower()


def _signature_for_repeat(text: str) -> str:
    s = _clean_block_text(text).lower()
    s = re.sub(r"\d+", "", s)
    s = re.sub(r"[\s\W_]+", "", s)
    return s


def _is_low_quality_block(text: str) -> bool:
    s = _clean_block_text(text)
    if not s:
        return True
    if "|" in s and re.search(r"[A-Za-z0-9\u4e00-\u9fff]", s):
        return False
    lower = s.lower()
    if "%pdf-" in lower or "endstream" in lower:
        return True
    if len(s) > 100 and "\\mathrm" in s:
        return True
    # Excessive symbol density often means OCR/binary residue.
    symbol_ratio = sum(1 for ch in s if not (ch.isalnum() or ("\u4e00" <= ch <= "\u9fff") or ch.isspace())) / max(1, len(s))
    if len(s) > 80 and symbol_ratio > 0.45:
        return True
    return False


def _drop_repeated_headers_footers(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_page: dict[int, list[dict[str, Any]]] = {}
    for b in blocks:
        by_page.setdefault(int(b.get("page_no") or 0), []).append(b)
    if len(by_page) < 3:
        return blocks

    for page_no, items in by_page.items():
        items.sort(key=lambda x: int(x.get("order_in_page") or 0))
        by_page[page_no] = items

    counter = Counter()
    for items in by_page.values():
        for b in items[:2] + items[-2:]:
            sig = _signature_for_repeat(str(b.get("text") or ""))
            if 6 <= len(sig) <= 80:
                counter[sig] += 1

    threshold = max(3, int(len(by_page) * 0.35))
    repeated = {sig for sig, cnt in counter.items() if cnt >= threshold}
    if not repeated:
        return blocks

    out: list[dict[str, Any]] = []
    for b in blocks:
        sig = _signature_for_repeat(str(b.get("text") or ""))
        order = int(b.get("order_in_page") or 0)
        page_items = by_page.get(int(b.get("page_no") or 0), [])
        is_edge = order <= 2 or order >= max(1, len(page_items) - 1)
        if is_edge and sig in repeated:
            continue
        out.append(b)
    return out


def _merge_cross_page_tables(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not tables:
        return []

    ordered = sorted(
        [t for t in tables if isinstance(t, dict)],
        key=lambda x: (int(x.get("page_no") or 0), int(x.get("order_in_page") or 0)),
    )
    merged: list[dict[str, Any]] = []

    for raw in ordered:
        page_no = int(raw.get("page_no") or 0)
        text = str(raw.get("raw_text") or "").strip()
        if page_no <= 0 or not text:
            continue
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            continue

        current = {
            "table_id": str(raw.get("table_id") or f"t_{page_no}_1"),
            "page_no": page_no,
            "page_start": page_no,
            "page_end": page_no,
            "order_in_page": int(raw.get("order_in_page") or 0),
            "raw_text": "\n".join(lines),
        }

        if not merged:
            merged.append(current)
            continue

        prev = merged[-1]
        prev_end = int(prev.get("page_end") or prev.get("page_no") or 0)
        if page_no != prev_end + 1:
            merged.append(current)
            continue

        prev_header = _table_header(prev.get("raw_text") or "")
        curr_header = _table_header(current.get("raw_text") or "")
        is_cont = _looks_cross_page_table(text)
        same_header = bool(prev_header and curr_header and prev_header == curr_header)
        if not (is_cont or same_header):
            merged.append(current)
            continue

        prev_lines = [line.strip() for line in str(prev.get("raw_text") or "").splitlines() if line.strip()]
        curr_lines = [line.strip() for line in text.splitlines() if line.strip()]
        curr_lines[0] = _strip_continuation_marker(curr_lines[0])
        append_lines = curr_lines[1:] if same_header and len(curr_lines) >= 2 else curr_lines
        if append_lines and prev_lines and append_lines[0] == prev_lines[-1]:
            append_lines = append_lines[1:]
        prev["raw_text"] = "\n".join([*prev_lines, *append_lines]).strip()
        prev["page_end"] = page_no

    return merged


def normalize_result(mineru_result: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    blocks: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []

    for page in mineru_result.get("pages", []):
        page_no = int(page.get("page_no", 0))

        for idx, block in enumerate(page.get("blocks", []), start=1):
            block_text = _clean_block_text(block.get("text", ""))
            if _is_toc_like(block_text):
                continue
            if _is_low_quality_block(block_text):
                continue
            blocks.append(
                {
                    "block_id": f"b_{page_no}_{idx}",
                    "page_no": page_no,
                    "block_type": block.get("type", "paragraph"),
                    "text": block_text,
                    "order_in_page": idx,
                }
            )

        for idx, table in enumerate(page.get("tables", []), start=1):
            raw_text = _clean_table_text(table.get("raw_text", ""))
            if _is_low_quality_block(raw_text):
                continue
            tables.append(
                {
                    "table_id": f"t_{page_no}_{idx}",
                    "page_no": page_no,
                    "raw_text": raw_text,
                    "order_in_page": idx,
                }
            )

    blocks = _drop_repeated_headers_footers(blocks)
    tables = _merge_cross_page_tables(tables)
    return blocks, tables
