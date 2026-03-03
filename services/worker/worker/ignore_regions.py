"""Ignore-region helpers (for QR/watermark area exclusion)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class IgnoreRegion:
    x0: float
    y0: float
    x1: float
    y1: float
    reason: str


def overlaps_ignore_regions(
    bbox: tuple[float, float, float, float],
    regions: list[IgnoreRegion],
    page_w: float,
    page_h: float,
) -> bool:
    x0, y0, x1, y1 = bbox
    for region in regions:
        rx0, ry0, rx1, ry1 = (
            region.x0 * page_w,
            region.y0 * page_h,
            region.x1 * page_w,
            region.y1 * page_h,
        )
        ix0, iy0 = max(x0, rx0), max(y0, ry0)
        ix1, iy1 = min(x1, rx1), min(y1, ry1)
        if ix1 <= ix0 or iy1 <= iy0:
            continue
        return True
    return False
