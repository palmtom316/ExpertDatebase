"""Layout crop helpers for dropping header/footer bands."""

from __future__ import annotations

from typing import Any


def crop_header_footer_blocks(
    blocks: list[dict[str, Any]],
    page_height: float,
    top_ratio: float = 0.10,
    bottom_ratio: float = 0.10,
) -> list[dict[str, Any]]:
    top_y = page_height * top_ratio
    bottom_y = page_height * (1.0 - bottom_ratio)
    kept: list[dict[str, Any]] = []

    for block in blocks:
        bbox = block.get("bbox") or block.get("box") or block.get("rect")
        if not bbox or len(bbox) != 4:
            kept.append(block)
            continue
        _, y0, _, y1 = bbox
        if y1 <= top_y:
            continue
        if y0 >= bottom_y:
            continue
        kept.append(block)
    return kept
