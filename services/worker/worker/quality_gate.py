"""Quality gate and document classification helpers."""

from __future__ import annotations

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


def classify_document(blocks: list[dict[str, Any]], tables: list[dict[str, Any]]) -> dict[str, Any]:
    corpus = "\n".join(str(x.get("text", "")) for x in blocks)
    corpus += "\n" + "\n".join(str(x.get("raw_text", "")) for x in tables)

    hints = {
        "qualification_doc": ["资格", "证书", "建造师", "执业"],
        "equipment_doc": ["设备", "主变", "开关", "清单"],
        "project_proof": ["项目", "合同", "中标", "业绩", "kV"],
    }

    best_type = "project_proof"
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
