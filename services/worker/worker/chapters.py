"""Chapter tree builder with degrade strategy C (page-first merge)."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

TITLE_PATTERNS = [
    re.compile(r"^第[一二三四五六七八九十0-9]+章"),
    re.compile(r"^[一二三四五六七八九十]+、"),
    re.compile(r"^\d+\.\d+"),
]


def _looks_like_title(text: str) -> bool:
    return any(p.search(text) for p in TITLE_PATTERNS)


def build_chapters(blocks: list[dict[str, Any]], min_merge_chars: int = 4000) -> list[dict[str, Any]]:
    if not blocks:
        return []

    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for block in blocks:
        by_page[int(block["page_no"])] += [block]

    pages = sorted(by_page.keys())

    # Chapter-first: split by strong titles.
    chapters: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for p in pages:
        page_blocks = sorted(by_page[p], key=lambda x: x["order_in_page"])
        for b in page_blocks:
            text = b.get("text", "")
            if _looks_like_title(text):
                if current:
                    chapters.append(current)
                current = {
                    "chapter_id": f"ch_{len(chapters)+1}",
                    "parent_id": None,
                    "title": text,
                    "level": 1,
                    "start_page": p,
                    "end_page": p,
                    "block_ids": [b["block_id"]],
                    "text": text,
                    "status": "normal",
                }
                continue

            if current is None:
                current = {
                    "chapter_id": "ch_1",
                    "parent_id": None,
                    "title": f"临时章节_{p}",
                    "level": 1,
                    "start_page": p,
                    "end_page": p,
                    "block_ids": [],
                    "text": "",
                    "status": "degenerate",
                }

            current["block_ids"].append(b["block_id"])
            current["end_page"] = p
            current["text"] = (current["text"] + "\n" + text).strip()

    if current:
        chapters.append(current)

    # Degrade strategy C: if chapters are too small, merge by pages into ~4k+ chars chunks.
    merged: list[dict[str, Any]] = []
    buf: dict[str, Any] | None = None
    for ch in chapters:
        if buf is None:
            buf = dict(ch)
            continue

        if len(buf.get("text", "")) < min_merge_chars:
            buf["end_page"] = ch["end_page"]
            buf["block_ids"] += ch["block_ids"]
            buf["text"] = (buf["text"] + "\n" + ch["text"]).strip()
            buf["status"] = "degenerate"
        else:
            merged.append(buf)
            buf = dict(ch)

    if buf:
        merged.append(buf)

    for i, ch in enumerate(merged, start=1):
        ch["chapter_id"] = f"ch_{i}"

    return merged
