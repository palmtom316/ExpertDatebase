"""Normalize MinerU output into block/table intermediate format."""

from __future__ import annotations

from typing import Any


def normalize_result(mineru_result: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    blocks: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []

    for page in mineru_result.get("pages", []):
        page_no = int(page.get("page_no", 0))

        for idx, block in enumerate(page.get("blocks", []), start=1):
            blocks.append(
                {
                    "block_id": f"b_{page_no}_{idx}",
                    "page_no": page_no,
                    "block_type": block.get("type", "paragraph"),
                    "text": str(block.get("text", "")).strip(),
                    "order_in_page": idx,
                }
            )

        for idx, table in enumerate(page.get("tables", []), start=1):
            tables.append(
                {
                    "table_id": f"t_{page_no}_{idx}",
                    "page_no": page_no,
                    "raw_text": str(table.get("raw_text", "")).strip(),
                    "order_in_page": idx,
                }
            )

    return blocks, tables
