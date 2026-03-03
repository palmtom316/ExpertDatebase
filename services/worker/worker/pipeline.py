"""Worker pipeline orchestration for MinerU post-processing."""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any

import yaml

from worker.chapters import build_chapters
from worker.chunking import chunk_chapters
from worker.explanation_parser import Page, parse_explanations_from_pages
from worker.normalize import normalize_result
from worker.quality_gate import assess_quality, classify_document, filter_chunks_for_indexing
from worker.table_threepack import build_table_threepack
from worker.table_struct import extract_table_struct
from worker.text_denoiser import denoise_pages_text


def _env_enabled(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw not in {"0", "false", "no", "off", ""}


def _config_path(name: str) -> Path:
    return Path(__file__).resolve().parents[3] / "shared" / "configs" / name


def _load_yaml_config(name: str, defaults: dict[str, Any]) -> dict[str, Any]:
    path = _config_path(name)
    if not path.exists():
        return dict(defaults)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return dict(defaults)
    if isinstance(data, dict):
        return data
    return dict(defaults)


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


def _raw_table_to_html(raw_text: str) -> str:
    lines = [line.strip() for line in str(raw_text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    rows: list[str] = []
    for line in lines:
        cells = [x.strip() for x in re.split(r"[|｜\t]", line) if x.strip()]
        if not cells:
            cells = [line]
        td = "".join(f"<td>{c}</td>" for c in cells)
        rows.append(f"<tr>{td}</tr>")
    return "<table>" + "".join(rows) + "</table>"


def _table_three_pack_from_module(
    doc_id: str,
    version_id: str,
    tables: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        table_id = str(table.get("table_id") or "").strip() or f"t_{int(table.get('page_no') or 0)}_1"
        page_no = int(table.get("page_start") or table.get("page_no") or 0)
        page_end = int(table.get("page_end") or page_no)
        raw_text = str(table.get("raw_text") or "").strip()
        if page_no <= 0 or not raw_text:
            continue
        table_html = _raw_table_to_html(raw_text)
        table_title = str(table.get("title") or f"表 {table_id}")
        try:
            threepack = build_table_threepack(
                doc_id=doc_id,
                page_no=page_no,
                table_html=table_html,
                table_title=table_title,
                table_id=table_id,
            )
        except Exception:  # noqa: BLE001
            continue
        for item in threepack:
            repr_type = str((item.payload or {}).get("table_repr") or "")
            if repr_type not in {"raw", "summary"}:
                continue
            source_type = "table_raw" if repr_type == "raw" else "table_summary"
            chunks.append(
                {
                    "chunk_id": str(item.chunk_id),
                    "doc_id": doc_id,
                    "version_id": version_id,
                    "chapter_id": f"table_p{page_no}",
                    "page_start": page_no,
                    "page_end": page_end,
                    "text": str(item.text or ""),
                    "block_ids": [],
                    "source_type": source_type,
                    "page_type": "table",
                    "table_repr": repr_type,
                    "table_id": table_id,
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


def _explanation_chunks_from_config(
    doc_id: str,
    version_id: str,
    normalized_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    defaults = {
        "explanation_start_regexes": [r"^\s*条\s*文\s*说\s*明\s*$", r"^\s*条文说明\s*$"],
        "clause_id_regex": r"^\s*(?P<id>\d+(?:\.\d+)+)(?:\((?P<sub>[0-9A-Za-z]+)\))?\s*(?P<rest>.*)$",
    }
    config = _load_yaml_config("explanation_rules.yaml", defaults=defaults)
    start_res = [str(x) for x in (config.get("explanation_start_regexes") or defaults["explanation_start_regexes"])]
    clause_re = str(config.get("clause_id_regex") or defaults["clause_id_regex"])

    by_page: dict[int, list[str]] = {}
    for block in normalized_blocks:
        page_no = int(block.get("page_no") or 0)
        text = str(block.get("text") or "").strip()
        if page_no <= 0 or not text:
            continue
        by_page.setdefault(page_no, []).append(text)
    pages = [Page(doc_id=doc_id, page_no=page_no, text="\n".join(lines)) for page_no, lines in sorted(by_page.items())]
    parsed = parse_explanations_from_pages(pages=pages, explanation_start_regexes=start_res, clause_id_regex=clause_re)

    out: list[dict[str, Any]] = []
    for idx, node in enumerate(parsed, start=1):
        text_parts = [str(node.title or "").strip(), str(node.body or "").strip()]
        text = "\n".join([x for x in text_parts if x]).strip()
        if not text:
            continue
        out.append(
            {
                "chunk_id": f"expcfg_{node.clause_id}_{idx}",
                "doc_id": doc_id,
                "version_id": version_id,
                "chapter_id": "explanation",
                "page_start": int(node.page_start or 0),
                "page_end": int(node.page_end or int(node.page_start or 0)),
                "text": text,
                "block_ids": [],
                "source_type": "explanation",
                "doc_type": "explanation",
                "clause_id": str(node.clause_id or ""),
            }
        )
    return out


def _apply_text_denoise(mineru_result: dict[str, Any]) -> dict[str, Any]:
    defaults = {
        "reject_line_regexes": [
            r"^\s*GB\s*\d+",
            r"^\s*UDC\b",
            r"标准分享网|工程师智库|公众号|二维码|长按|关注公众号|gcszhiku",
            r"^\s*第\s*\d+\s*页",
            r"^\s*\d+\s*/\s*\d+\s*$",
        ],
        "global_repeat": {"min_freq_ratio": 0.2, "max_line_len": 50},
    }
    config = _load_yaml_config("noise_rules.yaml", defaults=defaults)
    reject_line_regexes = [str(x) for x in (config.get("reject_line_regexes") or defaults["reject_line_regexes"])]
    global_repeat = config.get("global_repeat") or {}
    min_freq_ratio = float(global_repeat.get("min_freq_ratio") or defaults["global_repeat"]["min_freq_ratio"])
    max_line_len = int(global_repeat.get("max_line_len") or defaults["global_repeat"]["max_line_len"])

    pages = list(mineru_result.get("pages") or [])
    pages_text: list[str] = []
    for page in pages:
        lines = [str((block or {}).get("text") or "").strip() for block in (page.get("blocks") or [])]
        pages_text.append("\n".join([x for x in lines if x]))

    cleaned_pages, _, _ = denoise_pages_text(
        pages_text=pages_text,
        reject_line_regexes=reject_line_regexes,
        min_freq_ratio=min_freq_ratio,
        max_line_len=max_line_len,
    )

    updated_pages: list[dict[str, Any]] = []
    for page, cleaned_text in zip(pages, cleaned_pages):
        allowed = {line.strip() for line in str(cleaned_text).splitlines() if line.strip()}
        new_blocks: list[dict[str, Any]] = []
        for block in page.get("blocks") or []:
            text = str(block.get("text") or "").strip()
            if text and text not in allowed:
                continue
            new_blocks.append(block)
        new_page = dict(page)
        new_page["blocks"] = new_blocks
        updated_pages.append(new_page)
    return {**mineru_result, "pages": updated_pages}


def process_mineru_result(
    doc_id: str,
    version_id: str,
    mineru_result: dict[str, Any],
    vl_table_repairs_by_table_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    preprocessed = mineru_result
    if _env_enabled("WORKER_ENABLE_TEXT_DENOISE", default=False):
        preprocessed = _apply_text_denoise(mineru_result)

    normalized_blocks, normalized_tables = normalize_result(preprocessed)
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
        module_chunks = _table_three_pack_from_module(doc_id=doc_id, version_id=version_id, tables=normalized_tables)
        chunks_raw.extend(module_chunks or _table_three_pack_extra_chunks(doc_id=doc_id, version_id=version_id, tables=normalized_tables))

    if _env_enabled("WORKER_ENABLE_EXPLANATION_CHUNKS", default=False):
        config_chunks = _explanation_chunks_from_config(
            doc_id=doc_id,
            version_id=version_id,
            normalized_blocks=normalized_blocks,
        )
        chunks_raw.extend(config_chunks or _explanation_chunks(doc_id=doc_id, version_id=version_id, text_chunks=text_chunks))

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
