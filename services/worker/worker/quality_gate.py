"""Quality gate and document classification helpers."""

from __future__ import annotations

import os
import re
from typing import Any


def assess_quality(blocks: list[dict[str, Any]], tables: list[dict[str, Any]]) -> dict[str, Any]:
    text_len = sum(len(str(x.get("text", ""))) for x in blocks)
    block_count = len(blocks)
    table_count = len(tables)

    # Weighted quick quality estimate for blocking rollout.
    score = min(100, int(text_len / 40) + block_count * 4 + table_count * 8)
    if score >= 75:
        grade = "A"
    elif score >= 45:
        grade = "B"
    else:
        grade = "C"

    return {
        "grade": grade,
        "score": score,
        "block_count": block_count,
        "table_count": table_count,
        "text_len": text_len,
    }


def _readable_ratio(text: str) -> float:
    s = str(text or "")
    if not s:
        return 0.0
    keep = 0
    for ch in s:
        if ch.isalnum() or ("\u4e00" <= ch <= "\u9fff"):
            keep += 1
            continue
        if ch in "，。！？；：、（）()[]【】《》“”‘’+-*/%=._:;,\"' \n\t":
            keep += 1
    return keep / max(1, len(s))


def _looks_noisy_chunk(text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return True
    lower = s.lower()
    if "%pdf-" in lower or "obj<</filter/flatedecode" in lower or "endstream" in lower:
        return True
    latex_cmds = re.findall(r"\\[A-Za-z]+", s)
    if latex_cmds and len(s) >= 80:
        # Keep normal clauses that contain a small amount of OCR LaTeX residue
        # like "30\\mathrm{min}", but drop formula-dense chunks.
        cmd_density = sum(len(cmd) for cmd in latex_cmds) / max(1, len(s))
        stripped = re.sub(r"\\[A-Za-z]+\s*(?:\{[^{}]{0,40}\})?", " ", s)
        if len(latex_cmds) >= 4 and (cmd_density >= 0.10 or _readable_ratio(stripped) < 0.45):
            return True
    if len(s) >= 120 and _readable_ratio(s) < 0.5:
        return True
    return False


def _looks_noisy_table_row_chunk(text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return True
    if _looks_noisy_chunk(s):
        return True

    cells = [part.strip() for part in re.split(r"[|｜\t]", s) if part.strip()]
    if not cells:
        return _looks_noisy_chunk(s)

    noisy_cells = 0
    for cell in cells:
        if _looks_noisy_chunk(cell):
            noisy_cells += 1

    return noisy_cells >= max(2, len(cells) - 1)


def _has_evidence_signal(text: str) -> bool:
    s = str(text or "")
    if re.search(r"\b\d+\.\d+(?:\.\d+)?\b", s):
        return True
    if re.search(r"\d+\s*(?:kV|KV|千伏|MVA|万元|万|亿)", s, flags=re.IGNORECASE):
        return True
    if re.search(r"(证书|合同|项目|业主|负责人|断路器|电容器|验收|规范|标准|适用范围|适用|术语|定义|总则)", s):
        return True
    return False


def filter_chunks_for_indexing(chunks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Drop duplicate/noisy chunks before vector indexing."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    dropped_noise = 0
    dropped_short = 0
    dropped_dup = 0
    min_chars = max(10, int(os.getenv("QUALITY_GATE_MIN_CHARS", "100")))

    for chunk in chunks:
        text = str((chunk or {}).get("text") or "").strip()
        normalized = re.sub(r"\s+", " ", text)
        source_type = str((chunk or {}).get("source_type") or "").strip()
        signature = f"{source_type}|" + re.sub(r"[\s\W_]+", "", normalized.lower())
        is_table_row = source_type in {"table_row", "cross_page_table_row"} or str((chunk or {}).get("chunk_id") or "").startswith("tbl_")
        if signature and signature in seen:
            dropped_dup += 1
            continue

        if is_table_row:
            if _looks_noisy_table_row_chunk(text):
                dropped_noise += 1
                continue
        elif _looks_noisy_chunk(text):
            dropped_noise += 1
            continue

        if not is_table_row and len(normalized) < min_chars and not _has_evidence_signal(normalized):
            dropped_short += 1
            continue

        if signature:
            seen.add(signature)
        out.append(chunk)

    # Fallback: avoid empty index in tiny docs.
    if not out and chunks:
        out = list(chunks[: min(8, len(chunks))])

    return out, {
        "dropped_noise": dropped_noise,
        "dropped_short": dropped_short,
        "dropped_dup": dropped_dup,
    }


def classify_document(blocks: list[dict[str, Any]], tables: list[dict[str, Any]]) -> dict[str, Any]:
    corpus = "\n".join(str(x.get("text", "")) for x in blocks)
    corpus += "\n" + "\n".join(str(x.get("raw_text", "")) for x in tables)

    hints = {
        "规范规程": ["规范", "规程", "标准", "条文", "术语", "总则"],
        "投标文件": ["投标", "招标", "评标", "报价", "投标人"],
        "公司资质": ["资质", "营业执照", "许可", "认证", "体系证书"],
        "公司业绩": ["业绩", "项目", "中标", "合同", "竣工"],
        "公司资产": ["资产", "设备清单", "固定资产", "产权", "库存"],
        "人员资质": ["人员资质", "证书", "建造师", "执业", "岗位证"],
        "人员业绩": ["项目经理", "负责人", "履历", "个人业绩", "任职"],
        "优秀标书": ["优秀标书", "样板", "范本", "最佳实践"],
    }

    best_type = "规范规程"
    best_score = -1
    for doc_type, keys in hints.items():
        hit = sum(1 for key in keys if key in corpus)
        if hit > best_score:
            best_score = hit
            best_type = doc_type

    return {
        "doc_type": best_type,
        "confidence": max(0.3, min(0.99, 0.3 + best_score * 0.15)),
        "keyword_hits": best_score,
    }
