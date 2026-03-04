"""Chunking utilities for chapter text."""

from __future__ import annotations

import re
from typing import Any

_CLAUSE_PAT = re.compile(r"(?<!\d)(\d{1,2}(?:\.\d+){1,4}(?:\([0-9A-Za-z]+\))?)(?!\d)")
_TOP_CLAUSE_START_PAT = re.compile(r"^\s*(\d{1,2}(?:\.\d+){1,4}(?:\([0-9A-Za-z]+\))?)(?=\s|$|[:：])")
_SUBCLAUSE_START_PAT = re.compile(r"^\s*[\(（]([0-9]{1,2})[\)）](?=\s|$|[:：])")
_ITEM_START_PAT = re.compile(r"^\s*([0-9]{1,2})[)）](?=\s|$|[:：])")
_ITEM_SPACE_START_PAT = re.compile(r"^\s*([0-9]{1,2})(?=\s|$|[:：])")


def _extract_clause_id(text: str) -> str | None:
    m = _CLAUSE_PAT.search(str(text or ""))
    return m.group(1) if m else None


def _strip_clause_sub(clause_id: str) -> str:
    return re.sub(r"\([0-9A-Za-z]+\)$", "", str(clause_id or "").strip())


def _clause_parent_id(node_id: str) -> str:
    value = str(node_id or "").strip()
    if not value:
        return ""
    m_item = re.match(r"^(.+\([0-9A-Za-z]+\))\.\d+$", value)
    if m_item:
        return m_item.group(1)
    m_sub = re.match(r"^(.+)\([0-9A-Za-z]+\)$", value)
    if m_sub:
        return m_sub.group(1)
    parts = [p for p in value.split(".") if p]
    if len(parts) >= 2:
        return ".".join(parts[:-1])
    return ""


def _clause_level(node_id: str) -> int:
    value = str(node_id or "").strip()
    if not value:
        return 0
    m_item = re.match(r"^(.+\([0-9A-Za-z]+\))\.\d+$", value)
    if m_item:
        return _clause_level(m_item.group(1)) + 1
    base = _strip_clause_sub(value)
    level = len([p for p in base.split(".") if p])
    if re.search(r"\([0-9A-Za-z]+\)$", value):
        level += 1
    return level


def _segment_node_meta(line: str, root_clause: str | None, sub_clause: str | None) -> tuple[str | None, str | None, str | None, bool]:
    top = _TOP_CLAUSE_START_PAT.match(line)
    if top:
        node = top.group(1)
        root = _strip_clause_sub(node)
        sub = node if node != root else None
        return node, node, sub, True

    sub_m = _SUBCLAUSE_START_PAT.match(line)
    if sub_m and root_clause:
        node = f"{root_clause}({sub_m.group(1)})"
        return root_clause, node, node, True

    item_m = _ITEM_START_PAT.match(line)
    if item_m and (sub_clause or root_clause):
        parent = sub_clause or root_clause
        node = f"{parent}.{item_m.group(1)}"
        return parent, node, sub_clause, True

    # OCR/markdown lines often use "2 xxx" instead of "2) xxx" for list items.
    # Keep these lines under the current clause context.
    item_space_m = _ITEM_SPACE_START_PAT.match(line)
    if item_space_m and (sub_clause or root_clause):
        parent = sub_clause or root_clause
        node = f"{parent}.{item_space_m.group(1)}"
        return parent, node, sub_clause, True

    # Only use global clause-id fallback when no active clause context exists.
    # This avoids mislabeling lines like "2 ... 第2.1.1.4款 ..." as clause 2.1.1.4.
    if not (sub_clause or root_clause):
        fallback = _extract_clause_id(line)
        if fallback:
            root = _strip_clause_sub(fallback)
            sub = fallback if fallback != root else None
            return fallback, fallback, sub, True

    return sub_clause or root_clause, sub_clause or root_clause, sub_clause, False


def _split_by_clause_boundary(text: str) -> list[dict[str, Any]]:
    raw = str(text or "").strip()
    if not raw:
        return []
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return []

    root_clause: str | None = None
    sub_clause: str | None = None
    current: dict[str, Any] | None = None
    segments: list[dict[str, Any]] = []

    for line in lines:
        clause_id, node_id, next_sub, starts_new = _segment_node_meta(
            line=line,
            root_clause=root_clause,
            sub_clause=sub_clause,
        )
        if clause_id:
            root_clause = _strip_clause_sub(clause_id)
        sub_clause = next_sub

        if starts_new or current is None:
            if current and str(current.get("text") or "").strip():
                segments.append(current)
            node_key = str(node_id or clause_id or "")
            current = {
                "clause_id": clause_id,
                "clause_node_id": node_key or None,
                "clause_parent_id": _clause_parent_id(node_key) if node_key else "",
                "clause_level": _clause_level(node_key) if node_key else 0,
                "text": line,
            }
            continue

        current["text"] = f"{current.get('text', '')}\n{line}".strip()

    if current and str(current.get("text") or "").strip():
        segments.append(current)

    if segments:
        return segments

    cid = _extract_clause_id(raw)
    node = str(cid or "")
    return [
        {
            "clause_id": cid,
            "clause_node_id": node or None,
            "clause_parent_id": _clause_parent_id(node) if node else "",
            "clause_level": _clause_level(node) if node else 0,
            "text": raw,
        }
    ]


def _split_text(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    if len(raw) <= max_chars:
        return [raw]
    # Do not split on "." to preserve clause identifiers like "11.4.1".
    sentences = [s.strip() for s in re.split(r"(?<=[。！？；;!?\n])", raw) if s.strip()]
    if not sentences:
        sentences = [raw]

    out: list[str] = []
    current = ""
    for sent in sentences:
        if not current:
            current = sent
            continue
        if len(current) + len(sent) <= max_chars:
            current += sent
            continue
        out.append(current)
        if overlap_chars > 0:
            current = f"{current[-overlap_chars:]}{sent}"
        else:
            current = sent
    if current:
        out.append(current)
    return out


def _chapter_segments(chapter: dict[str, Any], max_chars: int, overlap_chars: int) -> list[dict[str, Any]]:
    block_rows = chapter.get("blocks")
    if isinstance(block_rows, list) and block_rows:
        segments: list[dict[str, Any]] = []
        carry_clause_id: str | None = None
        carry_clause_node_id: str | None = None
        carry_clause_parent_id: str | None = None
        carry_clause_level: int | None = None
        for row in block_rows:
            if not isinstance(row, dict):
                continue
            page_no = int(row.get("page_no") or chapter.get("start_page") or 0)
            block_id = str(row.get("block_id") or "").strip()
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            for clause_part in _split_by_clause_boundary(text):
                segment_text = str(clause_part.get("text") or "").strip()
                clause_id = str(clause_part.get("clause_id") or "").strip() or None
                clause_node_id = str(clause_part.get("clause_node_id") or clause_id or "").strip() or None
                clause_parent_id = str(clause_part.get("clause_parent_id") or "").strip()
                clause_level = int(clause_part.get("clause_level") or 0)

                # Continuation lines like "2 xxx" may contain inline references
                # (e.g., "第2.1.1.4款"), which should not override current clause context.
                if (
                    carry_clause_id is not None
                    and clause_id is not None
                    and clause_id != carry_clause_id
                    and not (
                        clause_id.startswith(f"{carry_clause_id}.")
                        or clause_id.startswith(f"{carry_clause_id}(")
                    )
                    and not _TOP_CLAUSE_START_PAT.match(segment_text)
                    and (
                        _ITEM_START_PAT.match(segment_text)
                        or _ITEM_SPACE_START_PAT.match(segment_text)
                        or _SUBCLAUSE_START_PAT.match(segment_text)
                    )
                ):
                    clause_id = carry_clause_id
                    clause_node_id = carry_clause_node_id or carry_clause_id
                    clause_parent_id = carry_clause_parent_id or ""
                    clause_level = int(carry_clause_level or 0)

                # OCR often splits numbered items into a new block without clause id.
                # Keep these fragments under the previous clause context in the same chapter.
                if clause_id is None and carry_clause_id is not None:
                    clause_id = carry_clause_id
                    clause_node_id = carry_clause_node_id or carry_clause_id
                    clause_parent_id = carry_clause_parent_id or ""
                    clause_level = int(carry_clause_level or 0)

                if clause_id is not None:
                    carry_clause_id = clause_id
                    carry_clause_node_id = clause_node_id
                    carry_clause_parent_id = clause_parent_id
                    carry_clause_level = clause_level

                for part in _split_text(segment_text, max_chars=max_chars, overlap_chars=overlap_chars):
                    segments.append(
                        {
                            "text": part,
                            "page_no": page_no,
                            "block_id": block_id,
                            "clause_id": clause_id,
                            "clause_node_id": clause_node_id,
                            "clause_parent_id": clause_parent_id,
                            "clause_level": clause_level,
                        }
                    )
        if segments:
            return segments

    # Fallback for old chapter shapes.
    text = str(chapter.get("text") or "").strip()
    if not text:
        return []
    page_no = int(chapter.get("start_page") or 0)
    block_ids = chapter.get("block_ids") if isinstance(chapter.get("block_ids"), list) else []
    block_id = str(block_ids[0] if block_ids else "").strip()
    clause_id = _extract_clause_id(text)
    clause_node_id = clause_id
    clause_parent_id = _clause_parent_id(str(clause_node_id or ""))
    clause_level = _clause_level(str(clause_node_id or ""))
    return [
        {
            "text": part,
            "page_no": page_no,
            "block_id": block_id,
            "clause_id": clause_id,
            "clause_node_id": clause_node_id,
            "clause_parent_id": clause_parent_id,
            "clause_level": clause_level,
        }
        for part in _split_text(text, max_chars, overlap_chars)
    ]


def chunk_chapters(
    doc_id: str,
    version_id: str,
    chapters: list[dict[str, Any]],
    min_chars: int = 220,
    max_chars: int = 420,
    overlap_chars: int = 80,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []

    for chapter in chapters:
        segments = _chapter_segments(chapter, max_chars=max_chars, overlap_chars=overlap_chars)
        if not segments:
            continue

        chunk_idx = 0
        current_text = ""
        current_pages: list[int] = []
        current_block_ids: list[str] = []
        current_clause_id: str | None = None
        current_clause_node_id: str | None = None
        current_clause_parent_id: str | None = None
        current_clause_level: int | None = None

        def flush_chunk() -> None:
            nonlocal chunk_idx, current_text, current_pages, current_block_ids
            nonlocal current_clause_id, current_clause_node_id, current_clause_parent_id, current_clause_level
            text = current_text.strip()
            if not text:
                current_text = ""
                current_pages = []
                current_block_ids = []
                current_clause_id = None
                current_clause_node_id = None
                current_clause_parent_id = None
                current_clause_level = None
                return
            chunk_idx += 1
            page_start = min(current_pages) if current_pages else int(chapter.get("start_page") or 0)
            page_end = max(current_pages) if current_pages else int(chapter.get("end_page") or page_start)
            resolved_node = current_clause_node_id or current_clause_id or _extract_clause_id(text)
            chunks.append(
                {
                    "chunk_id": f"{chapter['chapter_id']}_ck_{chunk_idx}",
                    "doc_id": doc_id,
                    "version_id": version_id,
                    "chapter_id": chapter["chapter_id"],
                    "page_start": page_start,
                    "page_end": page_end,
                    "text": text,
                    "block_ids": list(dict.fromkeys(current_block_ids)),
                    "clause_id": current_clause_id or _extract_clause_id(text),
                    "clause_node_id": resolved_node,
                    "clause_parent_id": current_clause_parent_id or _clause_parent_id(str(resolved_node or "")),
                    "clause_level": current_clause_level or _clause_level(str(resolved_node or "")),
                }
            )
            current_text = ""
            current_pages = []
            current_block_ids = []
            current_clause_id = None
            current_clause_node_id = None
            current_clause_parent_id = None
            current_clause_level = None

        for segment in segments:
            seg_text = str(segment.get("text") or "").strip()
            if not seg_text:
                continue
            seg_page = int(segment.get("page_no") or chapter.get("start_page") or 0)
            seg_block_id = str(segment.get("block_id") or "").strip()
            seg_clause_id = str(segment.get("clause_id") or "").strip() or None
            seg_clause_node_id = str(segment.get("clause_node_id") or seg_clause_id or "").strip() or None
            seg_clause_parent_id = str(segment.get("clause_parent_id") or "").strip() or None
            seg_clause_level = int(segment.get("clause_level") or 0) or None

            if not current_text:
                current_text = seg_text
                current_pages = [seg_page]
                current_block_ids = [seg_block_id] if seg_block_id else []
                current_clause_id = seg_clause_id
                current_clause_node_id = seg_clause_node_id
                current_clause_parent_id = seg_clause_parent_id
                current_clause_level = seg_clause_level
                continue

            if current_clause_id and seg_clause_id and current_clause_id != seg_clause_id:
                flush_chunk()
                current_text = seg_text
                current_pages = [seg_page]
                current_block_ids = [seg_block_id] if seg_block_id else []
                current_clause_id = seg_clause_id
                current_clause_node_id = seg_clause_node_id
                current_clause_parent_id = seg_clause_parent_id
                current_clause_level = seg_clause_level
                continue

            if current_clause_node_id and seg_clause_node_id and current_clause_node_id != seg_clause_node_id:
                flush_chunk()
                current_text = seg_text
                current_pages = [seg_page]
                current_block_ids = [seg_block_id] if seg_block_id else []
                current_clause_id = seg_clause_id
                current_clause_node_id = seg_clause_node_id
                current_clause_parent_id = seg_clause_parent_id
                current_clause_level = seg_clause_level
                continue

            if len(current_text) + 1 + len(seg_text) <= max_chars:
                current_text = f"{current_text}\n{seg_text}".strip()
                current_pages.append(seg_page)
                if seg_block_id:
                    current_block_ids.append(seg_block_id)
                if current_clause_id is None:
                    current_clause_id = seg_clause_id
                if current_clause_node_id is None:
                    current_clause_node_id = seg_clause_node_id
                if current_clause_parent_id is None:
                    current_clause_parent_id = seg_clause_parent_id
                if current_clause_level is None:
                    current_clause_level = seg_clause_level
                continue

            flush_chunk()
            current_text = seg_text
            current_pages = [seg_page]
            current_block_ids = [seg_block_id] if seg_block_id else []
            current_clause_id = seg_clause_id
            current_clause_node_id = seg_clause_node_id
            current_clause_parent_id = seg_clause_parent_id
            current_clause_level = seg_clause_level

        flush_chunk()

        # Merge trailing short chunk into previous chunk in the same chapter.
        if len(chunks) >= 2:
            tail = chunks[-1]
            prev = chunks[-2]
            if (
                tail.get("chapter_id") == chapter.get("chapter_id")
                and len(str(tail.get("text") or "")) < min_chars
                and (
                    not tail.get("clause_id")
                    or not prev.get("clause_id")
                    or str(tail.get("clause_id")) == str(prev.get("clause_id"))
                )
                and (
                    not tail.get("clause_node_id")
                    or not prev.get("clause_node_id")
                    or str(tail.get("clause_node_id")) == str(prev.get("clause_node_id"))
                )
            ):
                prev_text = str(prev.get("text") or "").strip()
                tail_text = str(tail.get("text") or "").strip()
                prev["text"] = f"{prev_text}\n{tail_text}".strip()
                prev["page_start"] = min(int(prev.get("page_start") or 0), int(tail.get("page_start") or 0))
                prev["page_end"] = max(int(prev.get("page_end") or 0), int(tail.get("page_end") or 0))
                if not prev.get("clause_id"):
                    prev["clause_id"] = tail.get("clause_id")
                if not prev.get("clause_node_id"):
                    prev["clause_node_id"] = tail.get("clause_node_id")
                if not prev.get("clause_parent_id"):
                    prev["clause_parent_id"] = tail.get("clause_parent_id")
                if not prev.get("clause_level"):
                    prev["clause_level"] = tail.get("clause_level")
                prev_ids = [str(x or "") for x in (prev.get("block_ids") or []) if str(x or "").strip()]
                tail_ids = [str(x or "") for x in (tail.get("block_ids") or []) if str(x or "").strip()]
                prev["block_ids"] = list(dict.fromkeys(prev_ids + tail_ids))
                chunks.pop()

    return chunks
