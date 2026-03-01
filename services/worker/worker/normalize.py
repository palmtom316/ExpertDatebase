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


def _signature_for_repeat(text: str) -> str:
    s = _clean_block_text(text).lower()
    s = re.sub(r"\d+", "", s)
    s = re.sub(r"[\s\W_]+", "", s)
    return s


def _is_low_quality_block(text: str) -> bool:
    s = _clean_block_text(text)
    if not s:
        return True
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
            raw_text = _clean_block_text(table.get("raw_text", ""))
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
    return blocks, tables
