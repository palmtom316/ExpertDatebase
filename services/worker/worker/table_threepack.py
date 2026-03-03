"""Table three-pack helpers: raw/summary/row facts."""

from __future__ import annotations

from dataclasses import dataclass
import html
import json
import re
from typing import Any


@dataclass
class TableChunk:
    chunk_id: str
    doc_id: str
    page_no: int
    text: str
    payload: dict[str, Any]


_TITLE_RE = re.compile(r"^\s*(表|TABLE)\s*(?P<no>\d+(?:\.\d+)*)\s*(?P<title>.+)$", re.IGNORECASE)


def infer_title(table_title: str | None) -> tuple[str | None, str | None]:
    if not table_title:
        return None, None
    m = _TITLE_RE.match(table_title.strip())
    if not m:
        return None, table_title.strip()
    return m.group("no"), m.group("title").strip()


def html_table_to_rows(table_html: str) -> list[list[str]]:
    rows: list[list[str]] = []
    tr_parts = re.split(r"</tr\s*>", str(table_html or ""), flags=re.IGNORECASE)
    for tr in tr_parts:
        if "<td" not in tr.lower():
            continue
        cells = re.split(r"</td\s*>", tr, flags=re.IGNORECASE)
        row: list[str] = []
        for cell in cells:
            m = re.search(r">(.+)$", cell, flags=re.DOTALL)
            if not m:
                continue
            text = re.sub(r"<[^>]+>", "", m.group(1))
            text = html.unescape(text).strip()
            if text:
                row.append(text)
        if row:
            rows.append(row)
    return rows


def build_table_summary(table_title: str, rows: list[list[str]]) -> str:
    parts = [str(table_title or "").strip()]
    if rows:
        parts.append("列：" + " / ".join(rows[0]))
        for row in rows[1:6]:
            parts.append(" | ".join(row))
    return "\n".join(parts).strip()


def build_row_facts(rows: list[list[str]]) -> list[dict[str, Any]]:
    if len(rows) < 2:
        return []
    header = rows[0]
    facts: list[dict[str, Any]] = []
    for row in rows[1:]:
        rec: dict[str, Any] = {}
        for i, h in enumerate(header):
            if i < len(row):
                rec[h] = row[i]
        if rec:
            facts.append(rec)
    return facts


def build_table_threepack(
    doc_id: str,
    page_no: int,
    table_html: str,
    table_title: str,
    table_id: str,
) -> list[TableChunk]:
    rows = html_table_to_rows(table_html)
    table_no, _ = infer_title(table_title)
    common = {
        "doc_id": doc_id,
        "page_no": page_no,
        "chunk_type": "table",
        "table_id": table_id,
        "table_no": table_no,
        "table_title": table_title,
    }

    chunks: list[TableChunk] = []
    chunks.append(
        TableChunk(
            chunk_id=f"{doc_id}::table_raw::{table_id}::{page_no}",
            doc_id=doc_id,
            page_no=page_no,
            text=table_html,
            payload={**common, "table_repr": "raw"},
        )
    )
    summary = build_table_summary(table_title, rows)
    chunks.append(
        TableChunk(
            chunk_id=f"{doc_id}::table_summary::{table_id}::{page_no}",
            doc_id=doc_id,
            page_no=page_no,
            text=summary,
            payload={**common, "table_repr": "summary"},
        )
    )
    for idx, rec in enumerate(build_row_facts(rows)):
        chunks.append(
            TableChunk(
                chunk_id=f"{doc_id}::table_row::{table_id}::{page_no}::{idx}",
                doc_id=doc_id,
                page_no=page_no,
                text=json.dumps(rec, ensure_ascii=False, separators=(",", ":")),
                payload={**common, "table_repr": "row", "row": rec},
            )
        )
    return chunks
