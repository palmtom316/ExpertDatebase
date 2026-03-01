"""Chat orchestration with mandatory citations."""

from __future__ import annotations

import os
import re
from typing import Any

from app.services.llm_router import LLMRouter
from app.services.search_service import SearchRepo, hybrid_search


def _citation_key(c: dict[str, Any]) -> tuple[str, int | None, int | None]:
    doc_name = str(c.get("doc_name") or "").strip()
    page_start = c.get("page_start")
    page_end = c.get("page_end")
    return (doc_name, page_start, page_end if page_end is not None else page_start)


def _merge_text(existing: str, extra: str, max_len: int = 500) -> str:
    a = str(existing or "").strip()
    b = str(extra or "").strip()
    if not b:
        return a
    if not a:
        return b[:max_len]
    if b in a:
        return a[:max_len]
    merged = f"{a}\n{b}"
    return merged[:max_len]


def _clean_text(value: Any, max_len: int = 1000) -> str:
    text = str(value or "")
    text = re.sub(r"\$[^$]{0,200}\$", " ", text)
    text = re.sub(r"\\[a-zA-Z]+\s*\{[^}]*\}", " ", text)
    text = re.sub(r"\\[a-zA-Z]+", " ", text)
    text = text.replace("{", " ").replace("}", " ")
    text = re.sub(r"\b\d{1,2}\.\d{1,2}(?:\.\d+)?\s*[A-Za-z][^；。]{0,100}\(\d{1,3}\)", " ", text)
    text = re.sub(r"[.…]{2,}\s*\(?\d{1,3}\)?", " ", text)
    # Remove control chars except \n and \t, then collapse whitespace.
    text = "".join(ch for ch in text if ch in ("\n", "\t") or ord(ch) >= 32)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def _readable_ratio(text: str) -> float:
    if not text:
        return 0.0
    keep = 0
    for ch in text:
        if ch.isalnum():
            keep += 1
            continue
        if "\u4e00" <= ch <= "\u9fff":
            keep += 1
            continue
        if ch in "，。！？；：、（）()[]【】《》“”‘’+-*/%=._:;,\"' ":
            keep += 1
    return keep / max(1, len(text))


def _pick_best_evidence_text(citation: dict[str, Any], max_len: int = 220) -> str:
    excerpt = _clean_text(citation.get("excerpt"), max_len=max_len)
    chunk_text = _clean_text(citation.get("chunk_text"), max_len=max_len)
    if _readable_ratio(excerpt) >= 0.55:
        return excerpt
    if _readable_ratio(chunk_text) >= 0.55:
        return chunk_text
    return excerpt or chunk_text


def _dedupe_citations(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, int | None, int | None], dict[str, Any]] = {}
    order: list[tuple[str, int | None, int | None]] = []
    for raw in citations:
        c = dict(raw or {})
        key = _citation_key(c)
        if key not in merged:
            c["excerpt"] = _clean_text(c.get("excerpt"), max_len=500)
            c["chunk_text"] = _clean_text(c.get("chunk_text"), max_len=1000)
            c["merged_count"] = 1
            merged[key] = c
            order.append(key)
            continue

        prev = merged[key]
        prev["excerpt"] = _merge_text(
            str(prev.get("excerpt") or ""),
            _clean_text(c.get("excerpt"), max_len=500),
        )
        prev["chunk_text"] = _merge_text(
            str(prev.get("chunk_text") or ""),
            _clean_text(c.get("chunk_text"), max_len=1000),
            max_len=1000,
        )
        prev["merged_count"] = int(prev.get("merged_count") or 1) + 1

    return [merged[k] for k in order]


def _build_expandable_evidence(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for c in citations:
        excerpt = str(c.get("excerpt", "") or "")
        chunk_text = str(c.get("chunk_text", "") or "")
        if excerpt and chunk_text and excerpt in chunk_text:
            pos = chunk_text.find(excerpt)
            context_before = chunk_text[max(0, pos - 80) : pos]
            context_after = chunk_text[pos + len(excerpt) : pos + len(excerpt) + 80]
        else:
            context_before = chunk_text[:80] if chunk_text else ""
            context_after = chunk_text[80:160] if chunk_text else ""
        output.append(
            {
                "doc_name": c.get("doc_name", ""),
                "page_start": c.get("page_start"),
                "page_end": c.get("page_end"),
                "context_before": context_before,
                "excerpt": excerpt,
                "context_after": context_after,
            }
        )
    return output


def _build_qa_prompt(question: str, citations: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for idx, c in enumerate(citations[:5], start=1):
        doc_name = str(c.get("doc_name") or "unknown")
        page = c.get("page_start")
        excerpt = _pick_best_evidence_text(c, max_len=220)
        if not excerpt:
            excerpt = "（该页未提取到可读文本）"
        blocks.append(f"[E{idx}] {doc_name} p.{page or '-'}: {excerpt}")

    evidence_text = "\n".join(blocks) if blocks else "（无可用证据）"
    return (
        "你是投标文档问答助手。必须仅基于证据回答，禁止编造。\n"
        "回答要求：\n"
        "1) 先给出直接答案（中文，1-3句，尽量具体到数值/条款/时间/主体）。\n"
        "2) 若证据不足，明确说明“证据不足”并指出缺什么信息。\n"
        "3) 不要输出与问题无关的泛化套话。\n\n"
        f"问题：{question}\n"
        f"证据：\n{evidence_text}"
    )


def _stub_specific_answer(question: str, citations: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for c in citations[:3]:
        doc_name = str(c.get("doc_name") or "unknown")
        page = c.get("page_start")
        excerpt = _pick_best_evidence_text(c, max_len=120)
        if not excerpt:
            continue
        lines.append(f"- {doc_name} p.{page or '-'}：{excerpt}")

    if not lines:
        return f"根据检索证据，问题“{question}”当前证据不足，建议查看原文后补充更多上下文。"
    return f"根据检索证据，问题“{question}”可参考以下具体内容：\n" + "\n".join(lines)


def chat_with_citations(
    question: str,
    repo: SearchRepo,
    entity_index: Any,
    runtime_config: dict[str, Any] | None = None,
    search_filter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    top_k = max(5, int(os.getenv("CHAT_SEARCH_TOP_K", "16")))
    search_res = hybrid_search(
        question=question,
        repo=repo,
        entity_index=entity_index,
        top_k=top_k,
        runtime_config=runtime_config,
        search_filter=search_filter,
    )
    citations = _dedupe_citations(search_res["citations"])
    prompt = _build_qa_prompt(question=question, citations=citations)

    router = LLMRouter()
    llm_res = router.route_and_generate(task_type="qa_generate", prompt=prompt, runtime_config=runtime_config)

    if not citations:
        answer = "未检索到可用证据，无法给出有引用支撑的回答。"
    elif str(llm_res.get("provider") or "") == "stub":
        answer = _stub_specific_answer(question=question, citations=citations)
    else:
        answer = str(llm_res.get("text") or "").strip() or _stub_specific_answer(question=question, citations=citations)

    return {
        "answer": answer,
        "citations": citations,
        "expandable_evidence": _build_expandable_evidence(citations),
        "llm": {"provider": llm_res["provider"], "model": llm_res["model"]},
    }
