"""Chunking utilities for chapter text."""

from __future__ import annotations

from typing import Any


def chunk_chapters(
    doc_id: str,
    version_id: str,
    chapters: list[dict[str, Any]],
    min_chars: int = 500,
    max_chars: int = 800,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []

    for chapter in chapters:
        text = chapter.get("text", "")
        if not text:
            continue

        if len(text) <= max_chars:
            parts = [text]
        else:
            parts = []
            start = 0
            while start < len(text):
                end = min(start + max_chars, len(text))
                parts.append(text[start:end])
                start = end

        for idx, part in enumerate(parts, start=1):
            if len(part) < min_chars and chunks:
                chunks[-1]["text"] += "\n" + part
                chunks[-1]["page_end"] = chapter["end_page"]
                continue

            chunks.append(
                {
                    "chunk_id": f"{chapter['chapter_id']}_ck_{idx}",
                    "doc_id": doc_id,
                    "version_id": version_id,
                    "chapter_id": chapter["chapter_id"],
                    "page_start": chapter["start_page"],
                    "page_end": chapter["end_page"],
                    "text": part,
                    "block_ids": chapter.get("block_ids", []),
                }
            )

    return chunks
