"""Chunking utilities for chapter text."""

from __future__ import annotations

import re
from typing import Any

_CLAUSE_PAT = re.compile(r"(?<!\d)(\d{1,2}(?:\.\d+){1,4}(?:\([0-9A-Za-z]+\))?)(?!\d)")


def _extract_clause_id(text: str) -> str | None:
    m = _CLAUSE_PAT.search(str(text or ""))
    return m.group(1) if m else None


def _split_by_clause_boundary(text: str) -> list[tuple[str | None, str]]:
    raw = str(text or "").strip()
    if not raw:
        return []
    marker_pat = re.compile(r"(?m)^\s*(\d{1,2}(?:\.\d+){1,4}(?:\([0-9A-Za-z]+\))?)(?=\s|$|[:：])")
    markers = list(marker_pat.finditer(raw))
    if len(markers) <= 1:
        cid = _extract_clause_id(raw)
        return [(cid, raw)]

    parts: list[tuple[str | None, str]] = []
    for idx, marker in enumerate(markers):
        start = marker.start()
        end = markers[idx + 1].start() if idx + 1 < len(markers) else len(raw)
        part = raw[start:end].strip()
        if not part:
            continue
        parts.append((marker.group(1), part))
    return parts or [(_extract_clause_id(raw), raw)]


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
        for row in block_rows:
            if not isinstance(row, dict):
                continue
            page_no = int(row.get("page_no") or chapter.get("start_page") or 0)
            block_id = str(row.get("block_id") or "").strip()
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            for clause_id, clause_part in _split_by_clause_boundary(text):
                for part in _split_text(clause_part, max_chars=max_chars, overlap_chars=overlap_chars):
                    segments.append({"text": part, "page_no": page_no, "block_id": block_id, "clause_id": clause_id})
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
    return [
        {"text": part, "page_no": page_no, "block_id": block_id, "clause_id": clause_id}
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

        def flush_chunk() -> None:
            nonlocal chunk_idx, current_text, current_pages, current_block_ids, current_clause_id
            text = current_text.strip()
            if not text:
                current_text = ""
                current_pages = []
                current_block_ids = []
                current_clause_id = None
                return
            chunk_idx += 1
            page_start = min(current_pages) if current_pages else int(chapter.get("start_page") or 0)
            page_end = max(current_pages) if current_pages else int(chapter.get("end_page") or page_start)
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
                }
            )
            current_text = ""
            current_pages = []
            current_block_ids = []
            current_clause_id = None

        for segment in segments:
            seg_text = str(segment.get("text") or "").strip()
            if not seg_text:
                continue
            seg_page = int(segment.get("page_no") or chapter.get("start_page") or 0)
            seg_block_id = str(segment.get("block_id") or "").strip()
            seg_clause_id = str(segment.get("clause_id") or "").strip() or None

            if not current_text:
                current_text = seg_text
                current_pages = [seg_page]
                current_block_ids = [seg_block_id] if seg_block_id else []
                current_clause_id = seg_clause_id
                continue

            if current_clause_id and seg_clause_id and current_clause_id != seg_clause_id:
                flush_chunk()
                current_text = seg_text
                current_pages = [seg_page]
                current_block_ids = [seg_block_id] if seg_block_id else []
                current_clause_id = seg_clause_id
                continue

            if len(current_text) + 1 + len(seg_text) <= max_chars:
                current_text = f"{current_text}\n{seg_text}".strip()
                current_pages.append(seg_page)
                if seg_block_id:
                    current_block_ids.append(seg_block_id)
                if current_clause_id is None:
                    current_clause_id = seg_clause_id
                continue

            flush_chunk()
            current_text = seg_text
            current_pages = [seg_page]
            current_block_ids = [seg_block_id] if seg_block_id else []
            current_clause_id = seg_clause_id

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
            ):
                prev_text = str(prev.get("text") or "").strip()
                tail_text = str(tail.get("text") or "").strip()
                prev["text"] = f"{prev_text}\n{tail_text}".strip()
                prev["page_start"] = min(int(prev.get("page_start") or 0), int(tail.get("page_start") or 0))
                prev["page_end"] = max(int(prev.get("page_end") or 0), int(tail.get("page_end") or 0))
                if not prev.get("clause_id"):
                    prev["clause_id"] = tail.get("clause_id")
                prev_ids = [str(x or "") for x in (prev.get("block_ids") or []) if str(x or "").strip()]
                tail_ids = [str(x or "") for x in (tail.get("block_ids") or []) if str(x or "").strip()]
                prev["block_ids"] = list(dict.fromkeys(prev_ids + tail_ids))
                chunks.pop()

    return chunks
