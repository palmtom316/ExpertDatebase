"""Worker pipeline orchestration for MinerU post-processing."""

from __future__ import annotations

import os
from typing import Any

from worker.chapters import build_chapters
from worker.chunking import chunk_chapters
from worker.normalize import normalize_result
from worker.quality_gate import assess_quality, classify_document, filter_chunks_for_indexing
from worker.table_struct import extract_table_struct


def _table_row_chunks(
    doc_id: str,
    version_id: str,
    tables: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        table_id = str(table.get("table_id") or "").strip()
        page_no = int(table.get("page_no") or 0)
        raw_text = str(table.get("raw_text") or "").strip()
        if not raw_text or page_no <= 0:
            continue
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        header = lines[0]
        for idx, row in enumerate(lines[1:], start=1):
            text = f"{header} | {row}".strip()
            chunks.append(
                {
                    "chunk_id": f"tbl_{table_id or page_no}_{idx}",
                    "doc_id": doc_id,
                    "version_id": version_id,
                    "chapter_id": f"table_p{page_no}",
                    "page_start": page_no,
                    "page_end": page_no,
                    "text": text,
                    "block_ids": [],
                    "source_type": "table_row",
                }
            )
    return chunks


def process_mineru_result(doc_id: str, version_id: str, mineru_result: dict[str, Any]) -> dict[str, Any]:
    normalized_blocks, normalized_tables = normalize_result(mineru_result)
    chapters = build_chapters(normalized_blocks)
    min_chars = max(100, int(os.getenv("CHUNK_MIN_CHARS", "220")))
    max_chars = max(min_chars + 20, int(os.getenv("CHUNK_MAX_CHARS", "420")))
    overlap_chars = max(0, int(os.getenv("CHUNK_OVERLAP_CHARS", "80")))
    chunks_raw = chunk_chapters(
        doc_id,
        version_id,
        chapters,
        min_chars=min_chars,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
    )
    chunks_raw.extend(_table_row_chunks(doc_id=doc_id, version_id=version_id, tables=normalized_tables))
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
