"""Cross-page table grouping/stitching helpers."""

from __future__ import annotations

from dataclasses import dataclass
import difflib
import html as html_lib
import re


@dataclass
class TableBlock:
    doc_id: str
    page_no: int
    table_title: str
    table_html: str
    header_sig: str


def header_signature(table_html: str) -> str:
    m = re.search(r"<tr[^>]*>(.*?)</tr\s*>", str(table_html or ""), flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    row = re.sub(r"<[^>]+>", " ", m.group(1))
    row = html_lib.unescape(row)
    row = " ".join(row.split())
    return row[:200]


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def group_crosspage_tables(
    blocks: list[TableBlock],
    header_sim_min: float = 0.7,
    max_pages_gap: int = 1,
) -> dict[str, list[TableBlock]]:
    groups: dict[str, list[TableBlock]] = {}
    idx = 0
    prev: TableBlock | None = None
    current_id: str | None = None

    for block in sorted(blocks, key=lambda x: (x.doc_id, x.page_no)):
        if prev and block.doc_id == prev.doc_id and (block.page_no - prev.page_no) <= max_pages_gap:
            if similarity(block.header_sig, prev.header_sig) >= header_sim_min or (
                block.table_title and block.table_title == prev.table_title
            ):
                assert current_id is not None
                groups[current_id].append(block)
                prev = block
                continue
        idx += 1
        current_id = f"tbl_{idx:04d}"
        groups[current_id] = [block]
        prev = block
    return groups


def stitch_table_group(group: list[TableBlock]) -> TableBlock:
    if not group:
        raise ValueError("empty group")
    base = group[0]
    merged = base.table_html
    for block in group[1:]:
        merged += "\n<!-- continued -->\n" + block.table_html
    return TableBlock(
        doc_id=base.doc_id,
        page_no=base.page_no,
        table_title=base.table_title,
        table_html=merged,
        header_sig=base.header_sig,
    )
