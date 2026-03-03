"""Worker pipeline orchestration for MinerU post-processing."""

from __future__ import annotations

import os
import re
from typing import Any

from worker.chapters import build_chapters
from worker.chunking import chunk_chapters
from worker.normalize import normalize_result
from worker.quality_gate import assess_quality, classify_document, filter_chunks_for_indexing
from worker.table_struct import extract_table_struct


def _env_enabled(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw not in {"0", "false", "no", "off", ""}


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
        page_no = int(table.get("page_start") or table.get("page_no") or 0)
        page_end = int(table.get("page_end") or page_no)
        raw_text = str(table.get("raw_text") or "").strip()
        if not raw_text or page_no <= 0:
            continue
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        header = lines[0]
        source_type = "cross_page_table_row" if page_end > page_no else "table_row"
        for idx, row in enumerate(lines[1:], start=1):
            text = f"{header} | {row}".strip()
            chunks.append(
                {
                    "chunk_id": f"tbl_{table_id or page_no}_{idx}",
                    "doc_id": doc_id,
                    "version_id": version_id,
                    "chapter_id": f"table_p{page_no}",
                    "page_start": page_no,
                    "page_end": page_end,
                    "text": text,
                    "block_ids": [],
                    "source_type": source_type,
                    "page_type": "table",
                    "table_repr": "row",
                    "table_id": table_id or f"t_{page_no}_1",
                    "row_index": idx,
                }
            )
    return chunks


def _table_summary_text(raw_text: str, max_rows: int = 3) -> str:
    lines = [line.strip() for line in str(raw_text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    header = lines[0]
    rows = lines[1 : max_rows + 1]
    if not rows:
        return f"表头: {header}"
    return f"表头: {header}；样例行: {'；'.join(rows)}"


def _table_three_pack_extra_chunks(
    doc_id: str,
    version_id: str,
    tables: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        table_id = str(table.get("table_id") or "").strip()
        page_no = int(table.get("page_start") or table.get("page_no") or 0)
        page_end = int(table.get("page_end") or page_no)
        raw_text = str(table.get("raw_text") or "").strip()
        if not raw_text or page_no <= 0:
            continue

        chunks.append(
            {
                "chunk_id": f"tblraw_{table_id or page_no}",
                "doc_id": doc_id,
                "version_id": version_id,
                "chapter_id": f"table_p{page_no}",
                "page_start": page_no,
                "page_end": page_end,
                "text": raw_text,
                "block_ids": [],
                "source_type": "table_raw",
                "page_type": "table",
                "table_repr": "raw",
                "table_id": table_id or f"t_{page_no}_1",
            }
        )

        summary = _table_summary_text(raw_text)
        if summary:
            chunks.append(
                {
                    "chunk_id": f"tblsum_{table_id or page_no}",
                    "doc_id": doc_id,
                    "version_id": version_id,
                    "chapter_id": f"table_p{page_no}",
                    "page_start": page_no,
                    "page_end": page_end,
                    "text": summary,
                    "block_ids": [],
                    "source_type": "table_summary",
                    "page_type": "table",
                    "table_repr": "summary",
                    "table_id": table_id or f"t_{page_no}_1",
                }
            )

    return chunks


def _explanation_chunks(
    doc_id: str,
    version_id: str,
    text_chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    clause_pat = re.compile(r"(?<!\d)(\d{1,2}(?:\.\d+){1,4}(?:\([0-9A-Za-z]+\))?)(?!\d)")

    for idx, chunk in enumerate(text_chunks, start=1):
        text = str(chunk.get("text") or "").strip()
        if "说明" not in text or ("条文说明" not in text and "说明:" not in text and "说明：" not in text):
            continue

        clause_id = str(chunk.get("clause_id") or "").strip()
        if not clause_id:
            m = clause_pat.search(text)
            clause_id = m.group(1) if m else ""
        if not clause_id:
            continue

        out.append(
            {
                "chunk_id": f"exp_{chunk.get('chapter_id', 'ch')}_{idx}",
                "doc_id": doc_id,
                "version_id": version_id,
                "chapter_id": str(chunk.get("chapter_id") or ""),
                "page_start": int(chunk.get("page_start") or 0),
                "page_end": int(chunk.get("page_end") or int(chunk.get("page_start") or 0)),
                "text": text,
                "block_ids": list(chunk.get("block_ids") or []),
                "source_type": "explanation",
                "doc_type": "explanation",
                "clause_id": clause_id,
            }
        )

    return out


def process_mineru_result(
    doc_id: str,
    version_id: str,
    mineru_result: dict[str, Any],
    vl_table_repairs_by_table_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_blocks, normalized_tables = normalize_result(mineru_result)
    chapters = build_chapters(normalized_blocks)
    min_chars = max(100, int(os.getenv("CHUNK_MIN_CHARS", "260")))
    max_chars = max(min_chars + 20, int(os.getenv("CHUNK_MAX_CHARS", "520")))
    overlap_chars = max(0, int(os.getenv("CHUNK_OVERLAP_CHARS", "80")))
    chunks_raw = chunk_chapters(
        doc_id,
        version_id,
        chapters,
        min_chars=min_chars,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
    )
    text_chunks = list(chunks_raw)
    chunks_raw.extend(_table_row_chunks(doc_id=doc_id, version_id=version_id, tables=normalized_tables))

    if _env_enabled("WORKER_ENABLE_TABLE_THREE_PACK", default=False):
        chunks_raw.extend(_table_three_pack_extra_chunks(doc_id=doc_id, version_id=version_id, tables=normalized_tables))

    if _env_enabled("WORKER_ENABLE_EXPLANATION_CHUNKS", default=False):
        chunks_raw.extend(_explanation_chunks(doc_id=doc_id, version_id=version_id, text_chunks=text_chunks))

    chunks, chunk_filter_stats = filter_chunks_for_indexing(chunks_raw)
    quality_gate = assess_quality(normalized_blocks, normalized_tables)
    classification = classify_document(normalized_blocks, normalized_tables)
    table_struct = extract_table_struct(normalized_tables, vl_repairs_by_table_id=vl_table_repairs_by_table_id)

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
