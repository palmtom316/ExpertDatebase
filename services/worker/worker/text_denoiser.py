"""Text denoise helpers based on regex and global-repeat lines."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re


@dataclass
class DenoiseStats:
    removed_by_regex: int
    removed_by_global_repeat: int
    kept: int


def denoise_pages_text(
    pages_text: list[str],
    reject_line_regexes: list[str],
    min_freq_ratio: float = 0.2,
    max_line_len: int = 50,
) -> tuple[list[str], DenoiseStats, dict[str, int]]:
    patterns = [re.compile(raw, re.IGNORECASE) for raw in reject_line_regexes]

    filtered_pages: list[list[str]] = []
    removed_by_regex = 0
    all_lines: list[str] = []

    for text in pages_text:
        kept_lines: list[str] = []
        for line in str(text or "").splitlines():
            item = line.strip()
            if not item:
                continue
            if any(p.search(item) for p in patterns):
                removed_by_regex += 1
                continue
            kept_lines.append(item)
            if len(item) <= max_line_len:
                all_lines.append(item)
        filtered_pages.append(kept_lines)

    n_pages = max(1, len(pages_text))
    freq = Counter(all_lines)
    threshold = max(1, int(min_freq_ratio * n_pages))
    repeat_lines = {line: count for line, count in freq.items() if count >= threshold and len(line) <= max_line_len}

    removed_by_global = 0
    cleaned_pages: list[str] = []
    for kept_lines in filtered_pages:
        out_lines: list[str] = []
        for item in kept_lines:
            if item in repeat_lines:
                removed_by_global += 1
                continue
            out_lines.append(item)
        cleaned_pages.append("\n".join(out_lines))

    stats = DenoiseStats(
        removed_by_regex=removed_by_regex,
        removed_by_global_repeat=removed_by_global,
        kept=sum(1 for page in cleaned_pages for line in page.splitlines() if line.strip()),
    )
    return cleaned_pages, stats, repeat_lines
