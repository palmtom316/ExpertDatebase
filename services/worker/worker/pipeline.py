"""Worker pipeline orchestration for MinerU post-processing."""

from __future__ import annotations

from typing import Any

from worker.chapters import build_chapters
from worker.chunking import chunk_chapters
from worker.normalize import normalize_result


def process_mineru_result(doc_id: str, version_id: str, mineru_result: dict[str, Any]) -> dict[str, Any]:
    normalized_blocks, normalized_tables = normalize_result(mineru_result)
    chapters = build_chapters(normalized_blocks)
    chunks = chunk_chapters(doc_id, version_id, chapters)

    return {
        "normalized_blocks": normalized_blocks,
        "normalized_tables": normalized_tables,
        "chapters": chapters,
        "chunks": chunks,
    }
