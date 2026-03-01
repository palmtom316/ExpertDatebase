"""Worker pipeline orchestration for MinerU post-processing."""

from __future__ import annotations

from typing import Any

from worker.chapters import build_chapters
from worker.chunking import chunk_chapters
from worker.normalize import normalize_result
from worker.quality_gate import assess_quality, classify_document, filter_chunks_for_indexing
from worker.table_struct import extract_table_struct


def process_mineru_result(doc_id: str, version_id: str, mineru_result: dict[str, Any]) -> dict[str, Any]:
    normalized_blocks, normalized_tables = normalize_result(mineru_result)
    chapters = build_chapters(normalized_blocks)
    chunks_raw = chunk_chapters(doc_id, version_id, chapters)
    chunks, chunk_filter_stats = filter_chunks_for_indexing(chunks_raw)
    quality_gate = assess_quality(normalized_blocks, normalized_tables)
    classification = classify_document(normalized_blocks, normalized_tables)
    table_struct = extract_table_struct(normalized_tables)

    return {
        "normalized_blocks": normalized_blocks,
        "normalized_tables": normalized_tables,
        "chapters": chapters,
        "chunks": chunks,
        "chunk_filter_stats": chunk_filter_stats,
        "quality_gate": quality_gate,
        "classification": classification,
        "table_struct": table_struct,
    }
