"""Chat orchestration with mandatory citations."""

from __future__ import annotations

import os
import re
from typing import Any

from app.services.llm_router import LLMRouter
from app.services.search_service import SearchRepo, hybrid_search


def _citation_key(c: dict[str, Any]) -> tuple[str, int | None, int | None, str, str, str]:
    doc_name = str(c.get("doc_name") or "").strip()
    page_start = c.get("page_start")
    page_end = c.get("page_end")
    source_type = str(c.get("source_type") or "").strip().lower()
    clause_id = str(c.get("clause_id") or "").strip()
    table_id = str(c.get("table_id") or "").strip()
    return (doc_name, page_start, page_end if page_end is not None else page_start, source_type, clause_id, table_id)


def _merge_text(existing: str, extra: str, max_len: int = 500) -> str:
    a = str(existing or "").strip()
    b = str(extra or "").strip()
    if not b:
        return a
    if not a:
        return b[:max_len]
    if b in a:
        return a[:max_len]
    if a in b:
        return b[:max_len]
    merged = f"{a}\n{b}"
    return merged[:max_len]


def _clean_text(value: Any, max_len: int = 1000) -> str:
    text = str(value or "")
    text = re.sub(r"table\s+images/\S+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<table[^>]*>.*?</table>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\$[^$]{0,200}\$", " ", text)
    text = re.sub(r"\\[a-zA-Z]+\s*\{[^}]*\}", " ", text)
    text = re.sub(r"\\[a-zA-Z]+", " ", text)
    text = text.replace("{", " ").replace("}", " ")
    text = re.sub(r"·\s*\d+\s*·", " ", text)
    text = re.sub(r"[：:]\s*\d+\s*·", " ", text)
    text = re.sub(r":\s*\d{1,3}\.\s*text\s*\d+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\btext\s+\d+\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\btext\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d{1,2}\.\d{1,2}(?:\.\d+)?\s*[A-Za-z][^；。]{0,100}\(\d{1,3}\)", " ", text)
    text = re.sub(r"[.…]{2,}\s*\(?\d{1,3}\)?", " ", text)
    # OCR often duplicates long spans back-to-back.
    text = re.sub(r"(.{24,140}?)\s+\1", r"\1", text)
    # Remove control chars except \n and \t, then collapse whitespace.
    text = "".join(ch for ch in text if ch in ("\n", "\t") or ord(ch) >= 32)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def _norm_segment_for_dedupe(segment: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", str(segment or "").strip())


def _dedupe_sentence_units(text: str) -> str:
    source = str(text or "").strip()
    if not source:
        return ""
    units = [u.strip() for u in re.split(r"(?<=[。！？；;])\s*", source) if u.strip()]
    if len(units) <= 1:
        return source
    out: list[str] = []
    seen: set[str] = set()
    for unit in units:
        norm = _norm_segment_for_dedupe(unit)
        if len(norm) >= 5:
            if norm in seen:
                continue
            if out and norm == _norm_segment_for_dedupe(out[-1]):
                continue
            seen.add(norm)
        out.append(unit)
    return " ".join(out).strip() or source


def _trim_section_summary_noise(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    first = cleaned.find("章节：")
    if first >= 0:
        second = cleaned.find("章节：", first + 3)
        if second > 0:
            cleaned = cleaned[:second].strip()
    cleaned = re.sub(r"[；;]\s*[；;]+", "；", cleaned)
    return cleaned.strip("；; ")


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
    raw_excerpt = str(citation.get("excerpt") or "")
    raw_chunk = str(citation.get("chunk_text") or "")
    source_type = str(citation.get("source_type") or "").strip().lower()
    if source_type == "section_summary":
        max_len = min(max_len, 360)
    excerpt = _clean_text(raw_excerpt, max_len=max_len)
    chunk_text = _clean_text(raw_chunk, max_len=max_len)
    chunk_readable = _readable_ratio(chunk_text) >= 0.55
    excerpt_readable = _readable_ratio(excerpt) >= 0.55
    # Prefer chunk text when stored excerpt is a short snapshot.
    if chunk_readable and len(raw_chunk) > len(raw_excerpt) + 30:
        picked = _dedupe_sentence_units(chunk_text)
    elif excerpt_readable:
        picked = _dedupe_sentence_units(excerpt)
    elif chunk_readable:
        picked = _dedupe_sentence_units(chunk_text)
    else:
        picked = _dedupe_sentence_units(excerpt or chunk_text)
    if source_type == "section_summary":
        picked = _trim_section_summary_noise(picked)
    return picked[:max_len]


def _dedupe_citations(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, int | None, int | None, str, str, str], dict[str, Any]] = {}
    order: list[tuple[str, int | None, int | None, str, str, str]] = []
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


def _constraint_risk_level(citation: dict[str, Any]) -> str:
    if bool(citation.get("is_mandatory")):
        return "high"
    text = f"{citation.get('excerpt') or ''} {citation.get('chunk_text') or ''}"
    if re.search(r"(不得|严禁|禁止)", text):
        return "high"
    if re.search(r"(必须|应当|应)", text):
        return "medium"
    return "low"


_CONSTRAINT_GUARD_TOKENS = ("必须", "应当", "应", "不得", "严禁", "禁止")
_CONDITION_GUARD_TOKENS = ("在", "当", "若", "如果", "前", "后", "时")


def _pick_full_evidence_text(citation: dict[str, Any], max_len: int = 4000) -> str:
    raw_excerpt = str(citation.get("excerpt") or "")
    raw_chunk = str(citation.get("chunk_text") or "")
    source_type = str(citation.get("source_type") or "").strip().lower()
    excerpt = _clean_text(raw_excerpt, max_len=max_len)
    chunk_text = _clean_text(raw_chunk, max_len=max_len)
    if chunk_text and excerpt and excerpt not in chunk_text and chunk_text not in excerpt:
        merged = f"{excerpt} {chunk_text}"
    else:
        merged = chunk_text or excerpt
    merged = _dedupe_sentence_units(merged)
    if source_type == "section_summary":
        merged = _trim_section_summary_noise(merged)
    return merged[:max_len]


def _split_constraint_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[。！？；;])\s*", str(text or "")) if s.strip()]


def _extract_constraint_guard_lines(text: str, max_lines: int = 6) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for sentence in _split_constraint_sentences(text):
        has_guard = any(tok in sentence for tok in _CONSTRAINT_GUARD_TOKENS)
        has_cond = any(tok in sentence for tok in _CONDITION_GUARD_TOKENS)
        if not has_guard and not has_cond:
            continue
        key = _norm_segment_for_dedupe(sentence)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(sentence)
        if len(out) >= max(1, int(max_lines)):
            break
    return out


def _augment_short_constraint_evidence(short_text: str, full_text: str, max_chars: int = 320) -> str:
    short = str(short_text or "").strip()
    full = str(full_text or "").strip()
    if not full:
        return short[:max_chars]
    full_has_guard = any(tok in full for tok in _CONSTRAINT_GUARD_TOKENS)
    short_has_guard = any(tok in short for tok in _CONSTRAINT_GUARD_TOKENS)
    if not full_has_guard or short_has_guard:
        return short[:max_chars]

    guard_line = next((s for s in _split_constraint_sentences(full) if any(tok in s for tok in _CONSTRAINT_GUARD_TOKENS)), "")
    if not guard_line:
        return short[:max_chars]
    if _norm_segment_for_dedupe(guard_line) in _norm_segment_for_dedupe(short):
        return short[:max_chars]
    merged = f"{short}；{guard_line}" if short else guard_line
    if len(merged) <= max_chars:
        return merged
    clipped = merged[:max_chars].rstrip(" ，,;；。")
    return f"{clipped}…"


def _build_constraint_items(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    short_max = max(120, int(os.getenv("CHAT_CONSTRAINT_EVIDENCE_SHORT_MAX_CHARS", "260")))
    full_max = max(1000, int(os.getenv("CHAT_CONSTRAINT_EVIDENCE_FULL_MAX_CHARS", "4000")))
    guard_max = max(2, int(os.getenv("CHAT_CONSTRAINT_GUARD_LINES_MAX", "6")))
    for c in citations:
        evidence_short = _pick_best_evidence_text(c, max_len=short_max)
        evidence_full = _pick_full_evidence_text(c, max_len=full_max)
        if not evidence_short and not evidence_full:
            continue
        if not evidence_short:
            evidence_short = _compact_clause_text(evidence_full, max_chars=short_max, max_sentences=3)
        evidence_short = _augment_short_constraint_evidence(
            short_text=evidence_short,
            full_text=evidence_full,
            max_chars=max(short_max + 40, 280),
        )
        guard_lines = _extract_constraint_guard_lines(evidence_full, max_lines=guard_max)
        items.append(
            {
                "doc_name": str(c.get("doc_name") or "").strip(),
                "page_start": c.get("page_start"),
                "page_end": c.get("page_end"),
                "clause_id": str(c.get("clause_id") or "").strip(),
                "is_mandatory": bool(c.get("is_mandatory")),
                "risk_level": _constraint_risk_level(c),
                # Backward-compatible display field.
                "evidence": evidence_short,
                "evidence_short": evidence_short,
                # Full-text basis for downstream writing/constrained generation.
                "evidence_full": evidence_full,
                "evidence_guard_lines": guard_lines,
            }
        )
    return items


def _build_constraint_model_items(constraints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    model_items: list[dict[str, Any]] = []
    for item in constraints:
        model_items.append(
            {
                "doc_name": item.get("doc_name", ""),
                "page_start": item.get("page_start"),
                "page_end": item.get("page_end"),
                "clause_id": item.get("clause_id", ""),
                "is_mandatory": bool(item.get("is_mandatory")),
                "risk_level": item.get("risk_level", "low"),
                "evidence": str(item.get("evidence_full") or item.get("evidence") or ""),
                "guard_lines": list(item.get("evidence_guard_lines") or []),
            }
        )
    return model_items


def _build_constraint_summary(question: str, constraints: list[dict[str, Any]]) -> str:
    if not constraints:
        return f"问题“{question}”当前证据不足，未能提取到可审计的约束条款。"
    high = sum(1 for item in constraints if item.get("risk_level") == "high")
    mandatory = sum(1 for item in constraints if item.get("is_mandatory"))
    return (
        f"共提取 {len(constraints)} 条约束，其中强制性条款 {mandatory} 条，"
        f"高风险条款 {high} 条。请逐条核对引用页码后执行。"
    )


def _build_qa_prompt(question: str, citations: list[dict[str, Any]]) -> str:
    has_explanation = any(
        str(c.get("source_type") or "").strip().lower() == "explanation"
        or str(c.get("route") or "").strip().lower() == "explanation_sibling"
        for c in citations
    )
    blocks: list[str] = []
    for idx, c in enumerate(citations[:6], start=1):
        doc_name = str(c.get("doc_name") or "unknown")
        page = c.get("page_start")
        source_type = str(c.get("source_type") or "").strip().lower()
        evidence_tag = "条文说明" if source_type == "explanation" else "条文正文"
        excerpt = _pick_best_evidence_text(c, max_len=220)
        if not excerpt:
            excerpt = "（该页未提取到可读文本）"
        blocks.append(f"[E{idx}] {evidence_tag} | {doc_name} p.{page or '-'}: {excerpt}")

    evidence_text = "\n".join(blocks) if blocks else "（无可用证据）"
    explanation_rule = "4) 若证据含“条文说明”，必须单列“条文说明”并给出对应解释要点。\n" if has_explanation else ""
    return (
        "你是投标文档问答助手。必须仅基于证据回答，禁止编造。\n"
        "回答要求：\n"
        "1) 先给出直接答案（中文，1-3句，尽量具体到数值/条款/时间/主体）。\n"
        "2) 若证据不足，明确说明“证据不足”并指出缺什么信息。\n"
        "3) 不要输出与问题无关的泛化套话。\n\n"
        f"{explanation_rule}"
        f"问题：{question}\n"
        f"证据：\n{evidence_text}"
    )


def _stub_specific_answer(question: str, citations: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for c in citations[:8]:
        doc_name = str(c.get("doc_name") or "unknown")
        page = c.get("page_start")
        excerpt = _pick_best_evidence_text(c, max_len=120)
        if not excerpt:
            continue
        lines.append(f"- {doc_name} p.{page or '-'}：{excerpt}")

    if not lines:
        return f"根据检索证据，问题“{question}”当前证据不足，建议查看原文后补充更多上下文。"
    return f"根据检索证据，问题“{question}”可参考以下具体内容：\n" + "\n".join(lines)


def _is_explanation_citation(citation: dict[str, Any]) -> bool:
    source_type = str(citation.get("source_type") or "").strip().lower()
    route = str(citation.get("route") or "").strip().lower()
    return source_type == "explanation" or route == "explanation_sibling"


_CLAUSE_ID_PATTERN = re.compile(r"(?<!\d)\d{1,2}(?:\.\d+){1,4}(?:\([0-9A-Za-z]+\))?(?!\d)")
_LISTING_HINTS = ("有哪些", "包括哪些", "包含哪些", "列出", "清单", "哪些要求", "哪些规定")
_INSTALL_PRIORITY_ROOTS = ("4.6", "4.8")


def _extract_clause_ids_from_question(question: str) -> list[str]:
    q = str(question or "").strip()
    if not q:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in _CLAUSE_ID_PATTERN.findall(q):
        clause = re.sub(r"\([0-9A-Za-z]+\)$", "", str(raw or "").strip())
        if not clause or clause in seen:
            continue
        seen.add(clause)
        out.append(clause)
    return out


def _should_trust_explicit_clause_ids(question: str) -> bool:
    q = str(question or "").strip()
    if not q:
        return False
    if any(token in q for token in ("没查询到", "没有查询到", "回复", "还是", "但是", "却")):
        return False
    return True


def _is_listing_clause_query(question: str) -> bool:
    q = str(question or "").strip().lower()
    if not q:
        return False
    return any(token in q for token in _LISTING_HINTS)


def _should_use_fixed_clause_format(question: str, citations: list[dict[str, Any]]) -> bool:
    if not citations:
        return False
    has_clause = any(str(c.get("clause_id") or "").strip() for c in citations)
    if not has_clause:
        return False
    q = str(question or "").strip()
    if not q:
        return False
    if _CLAUSE_ID_PATTERN.search(q):
        return True
    return any(token in q for token in ["条文", "规定", "服从", "应符合"])


def _compact_clause_text(text: str, max_chars: int = 260, max_sentences: int = 3) -> str:
    source = _dedupe_sentence_units(str(text or "").strip())
    if not source:
        return ""
    units = [u.strip() for u in re.split(r"(?<=[。！？；;])\s*", source) if u.strip()]
    if not units:
        units = [source]
    out: list[str] = []
    for unit in units:
        norm = _norm_segment_for_dedupe(unit)
        if out and norm and norm == _norm_segment_for_dedupe(out[-1]):
            continue
        out.append(unit)
        if len(out) >= max(1, int(max_sentences)):
            break
    joined = " ".join(out).strip()
    if len(joined) <= max_chars:
        return joined
    clipped = joined[:max_chars].rstrip(" ，,;；。")
    return f"{clipped}…"


def _format_clause_line(citation: dict[str, Any], max_len: int = 520, concise: bool = False) -> str:
    text = _pick_best_evidence_text(citation, max_len=max_len)
    if not text:
        text = "（该页未提取到可读文本）"
    if concise:
        source_type = str(citation.get("source_type") or "").strip().lower()
        is_summary = source_type == "section_summary"
        text = _compact_clause_text(
            text=text,
            max_chars=min(max_len, 220 if is_summary else 280),
            max_sentences=2 if is_summary else 3,
        )
    doc_name = str(citation.get("doc_name") or "unknown").strip()
    page = citation.get("page_start")
    page_text = f"p.{page}" if page is not None else "p.-"
    return f"{text}（{doc_name} {page_text}）"


def _pick_section_lines(
    citations: list[dict[str, Any]],
    limit: int = 3,
    concise: bool = False,
    max_len: int = 520,
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for c in citations:
        line = _format_clause_line(citation=c, max_len=max_len, concise=concise)
        key = re.sub(r"\s+", "", line)
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
        if len(out) >= limit:
            break
    return out


def _repo_payload_to_citation(payload: dict[str, Any], route_default: str = "clause_sibling") -> dict[str, Any]:
    return {
        "doc_name": payload.get("doc_name", ""),
        "doc_id": payload.get("doc_id", ""),
        "page_start": payload.get("page_start"),
        "page_end": payload.get("page_end"),
        "excerpt": payload.get("excerpt", ""),
        "chunk_text": payload.get("chunk_text", ""),
        "route": payload.get("route", route_default),
        "source_type": payload.get("source_type", ""),
        "page_type": payload.get("page_type", ""),
        "table_id": payload.get("table_id"),
        "row_index": payload.get("row_index"),
        "clause_id": payload.get("clause_id") or payload.get("clause_no"),
        "table_repr": payload.get("table_repr"),
    }


def _env_enabled(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw not in {"0", "false", "no", "off", ""}


def _clause_root(clause_id: str) -> str:
    clause = re.sub(r"\([0-9A-Za-z]+\)$", "", str(clause_id or "").strip())
    parts = [p for p in clause.split(".") if p]
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return clause


def _clause_major(clause_id: str) -> str:
    clause = re.sub(r"\([0-9A-Za-z]+\)$", "", str(clause_id or "").strip())
    parts = [p for p in clause.split(".") if p]
    return parts[0] if parts else ""


def _pick_target_clauses(question: str, citations: list[dict[str, Any]]) -> tuple[list[str], bool]:
    explicit = _extract_clause_ids_from_question(question) if _should_trust_explicit_clause_ids(question) else []
    if explicit:
        return explicit, False

    ranked = _rank_clause_ids(question=question, citations=citations)
    if not ranked:
        return [], False

    listing = _is_listing_clause_query(question)
    if not listing:
        return [ranked[0]], False

    ranked_roots = _rank_clause_roots_for_listing(question=question, citations=citations)
    if not ranked_roots:
        return [], False
    root_texts = _collect_root_texts(citations)
    listing_limit = max(2, int(os.getenv("CHAT_CLAUSE_TEMPLATE_LISTING_FAMILIES", "3")))
    target_roots: list[str] = []
    install_listing = _question_has_install_intent(question) and not _question_has_vacuum_terms(question)
    if install_listing:
        citation_roots = {_clause_root(str(c.get("clause_id") or "")) for c in citations if str(c.get("clause_id") or "").strip()}
        for anchor in _INSTALL_PRIORITY_ROOTS:
            if anchor in ranked_roots or anchor in citation_roots:
                if anchor not in target_roots:
                    target_roots.append(anchor)
        for hints in (_INSTALL_INTERNAL_HINTS, _INSTALL_ACCESSORY_HINTS):
            root = next((r for r in ranked_roots if any(h in str(root_texts.get(r) or "") for h in hints)), "")
            if root and root not in target_roots:
                target_roots.append(root)
    for root in ranked_roots:
        if not root or root in target_roots:
            continue
        target_roots.append(root)
        if len(target_roots) >= listing_limit:
            break
    return target_roots, True


def _attach_clause_family_siblings(question: str, citations: list[dict[str, Any]], repo: SearchRepo) -> list[dict[str, Any]]:
    if not citations or not _env_enabled("CHAT_CLAUSE_TEMPLATE_ATTACH_SIBLINGS", default=True):
        return citations
    if not _should_use_fixed_clause_format(question=question, citations=citations):
        return citations

    fetch_fn = getattr(repo, "fetch_by_filter", None)
    if not callable(fetch_fn):
        return citations

    targets, family_mode = _pick_target_clauses(question=question, citations=citations)
    if not targets:
        return citations

    listing = _is_listing_clause_query(question)
    sibling_limit = max(4, int(os.getenv("CHAT_CLAUSE_TEMPLATE_SIBLING_LIMIT", "12")))
    if listing:
        sibling_limit = max(sibling_limit, int(os.getenv("CHAT_CLAUSE_TEMPLATE_SIBLING_LIMIT_LISTING", "16")))

    out: list[dict[str, Any]] = []
    seen_index: dict[tuple[str, int | None, int | None, str, str, str], int] = {}

    def _add_or_merge(c: dict[str, Any]) -> None:
        key = _citation_key(c)
        if key in seen_index:
            idx = seen_index[key]
            prev = out[idx]
            prev["excerpt"] = _merge_text(str(prev.get("excerpt") or ""), str(c.get("excerpt") or ""), max_len=1000)
            prev["chunk_text"] = _merge_text(str(prev.get("chunk_text") or ""), str(c.get("chunk_text") or ""), max_len=4000)
            prev["merged_count"] = int(prev.get("merged_count") or 1) + 1
            return
        seen_index[key] = len(out)
        out.append(c)

    for c in citations:
        _add_or_merge(c)

    primary_doc_id = next((str(c.get("doc_id") or "").strip() for c in citations if str(c.get("doc_id") or "").strip()), "")
    for target in targets:
        must = [
            {"key": "clause_id", "match": {"value": target}},
            {"key": "source_type", "match": {"any": ["text", "explanation", "section_summary"]}},
        ]
        if primary_doc_id:
            must.append({"key": "doc_id", "match": {"value": primary_doc_id}})
        sibling_filter = {"must": must}
        try:
            sibling_hits = fetch_fn(filter_json=sibling_filter, limit=sibling_limit) or []
        except Exception:  # noqa: BLE001
            sibling_hits = []
        if family_mode and not sibling_hits:
            keyword_fn = getattr(repo, "keyword_search", None)
            if callable(keyword_fn):
                try:
                    sibling_hits = keyword_fn(query_text=target, filter_json=sibling_filter, limit=sibling_limit) or []
                except Exception:  # noqa: BLE001
                    sibling_hits = []
        for hit in sibling_hits:
            payload = (hit or {}).get("payload") if isinstance(hit, dict) else None
            if not isinstance(payload, dict):
                continue
            citation = _repo_payload_to_citation(payload=payload)
            clause_id = str(citation.get("clause_id") or "")
            if family_mode:
                if not _same_clause_family(clause_id, target):
                    continue
            elif not _same_clause_family(clause_id, target):
                continue
            _add_or_merge(citation)

    out.sort(
        key=lambda x: (
            str(x.get("clause_id") or ""),
            int(x.get("page_start") or 0),
            str(x.get("source_type") or ""),
        )
    )
    return out


def _citation_text_for_match(citation: dict[str, Any], max_len: int = 600) -> str:
    return _pick_best_evidence_text(citation=citation, max_len=max_len).lower()


_CN_STOP_TERMS = {
    "哪些",
    "哪些规定",
    "有哪些",
    "有什么",
    "规定",
    "要求",
    "相关",
    "有关",
    "请问",
    "一下",
    "说明",
    "什么",
    "怎么",
    "如何",
    "应当",
    "应该",
    "是否",
}
_CN_STOP_CHARS = set("的了吗呢吧啊呀和及并且或与在对将把为于被就都其")


def _clean_question_for_terms(question: str) -> str:
    q = str(question or "").lower()
    q = _CLAUSE_ID_PATTERN.sub(" ", q)
    q = re.sub(r"(回复|回答|查询到|没查询到|没有查询到|为什么|还是|但是|却)", " ", q)
    q = re.sub(r"(有哪些规定|有哪(?:些)?规定|有哪些|有哪|哪些|规定|要求|什么|如何|怎么|请问)", " ", q)
    return re.sub(r"\s+", "", q)


def _split_cn_run(run: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    for ch in run:
        if ch in _CN_STOP_CHARS:
            if len(buf) >= 2:
                parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    if len(buf) >= 2:
        parts.append("".join(buf))
    return parts


def _valid_cn_term(term: str) -> bool:
    t = str(term or "").strip()
    if len(t) < 2:
        return False
    if t in _CN_STOP_TERMS:
        return False
    if re.search(r"(哪些|有哪|规定|要求|什么|如何|怎么|请问)", t):
        return False
    if len(t) <= 3 and re.search(r"[有哪些]", t):
        return False
    if all(ch in _CN_STOP_CHARS for ch in t):
        return False
    return True


def _extract_question_match_terms(question: str) -> list[str]:
    q = _clean_question_for_terms(question)
    terms: list[str] = []
    runs = re.findall(r"[\u4e00-\u9fff]{2,36}", q)
    for run in runs:
        segments = _split_cn_run(run)
        if not segments:
            segments = [run]
        for seg in segments:
            seg_len = len(seg)
            if seg_len <= 8 and _valid_cn_term(seg):
                terms.append(seg)
            for n in (2, 3, 4):
                if seg_len < n:
                    continue
                for i in range(0, seg_len - n + 1):
                    gram = seg[i : i + n]
                    if _valid_cn_term(gram):
                        terms.append(gram)
    out: list[str] = []
    seen: set[str] = set()
    for t in terms:
        x = t.strip()
        if len(x) < 2 or x in seen:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]+", x) and not _valid_cn_term(x):
            continue
        seen.add(x)
        out.append(x)
    return out


def _question_has_install_intent(question: str) -> bool:
    q = str(question or "").strip()
    if not q:
        return False
    return "安装" in q


def _question_has_vacuum_terms(question: str) -> bool:
    q = str(question or "").strip().lower()
    if not q:
        return False
    return any(token in q for token in ("真空", "注油", "抽真空", "氮气"))


def _question_to_citation_relevance(question: str, citation: dict[str, Any]) -> float:
    terms = _extract_question_match_terms(question)
    if not terms:
        return 0.0
    text = _citation_text_for_match(citation)
    if not text:
        return 0.0
    score = 0.0
    for term in terms:
        cnt = text.count(term)
        if cnt <= 0:
            continue
        score += (1.0 + min(len(term), 8) * 0.1) * min(cnt, 3)
    if _question_has_install_intent(question) and "安装" in text:
        score += 1.6
    if _question_has_install_intent(question) and not _question_has_vacuum_terms(question):
        if any(token in text for token in ("真空", "注油", "抽真空", "氮气")):
            score -= 0.9
    return score


def _clause_depth(clause_id: str) -> int:
    value = re.sub(r"\([0-9A-Za-z]+\)$", "", str(clause_id or "").strip())
    return len([p for p in value.split(".") if p])


def _same_clause_family(clause_id: str, root_clause: str) -> bool:
    cid = str(clause_id or "").strip()
    root = str(root_clause or "").strip()
    if not cid or not root:
        return False
    return cid == root or cid.startswith(f"{root}.") or cid.startswith(f"{root}(")


_VACUUM_HINTS = ("真空", "注油", "抽真空", "氮气", "储油柜")
_INSTALL_INTERNAL_HINTS = ("内部安装、连接", "内部安装")
_INSTALL_ACCESSORY_HINTS = (
    "本体及附件安装",
    "附件安装",
    "冷却装置的安装",
    "套管的安装",
    "压力释放装置",
)


def _citation_clause_weight(question: str, citation: dict[str, Any], listing_query: bool = False) -> float:
    clause_id = str(citation.get("clause_id") or "").strip()
    source_type = str(citation.get("source_type") or "").strip().lower()
    text = _citation_text_for_match(citation)
    weight = 1.0
    if not _is_explanation_citation(citation):
        weight += 1.0
    if source_type == "text":
        weight += 0.6
    if source_type == "section_summary":
        weight -= 1.4
        if listing_query and _clause_depth(clause_id) <= 2:
            # Listing questions rely on section-level anchors.
            weight += 1.0
    weight += min(0.6, _clause_depth(clause_id) * 0.2)
    weight += min(12.0, _question_to_citation_relevance(question=question, citation=citation))
    if listing_query and _question_has_install_intent(question) and not _question_has_vacuum_terms(question):
        if any(token in text for token in _VACUUM_HINTS):
            weight -= 1.8
    return weight


def _rank_clause_ids(question: str, citations: list[dict[str, Any]]) -> list[str]:
    scores: dict[str, float] = {}
    order: list[str] = []
    for c in citations:
        clause_id = str(c.get("clause_id") or "").strip()
        if not clause_id:
            continue
        if clause_id not in scores:
            scores[clause_id] = 0.0
            order.append(clause_id)
        scores[clause_id] += _citation_clause_weight(question=question, citation=c, listing_query=False)
    if not scores:
        return []
    return sorted(
        order,
        key=lambda cid: (
            -scores[cid],
            -_clause_depth(cid),
            cid,
        ),
    )


def _pick_dominant_clause_id(question: str, citations: list[dict[str, Any]]) -> str:
    ranked = _rank_clause_ids(question=question, citations=citations)
    if not ranked:
        return ""
    return ranked[0]


def _collect_root_texts(citations: list[dict[str, Any]]) -> dict[str, str]:
    by_root: dict[str, list[str]] = {}
    for c in citations:
        clause_id = str(c.get("clause_id") or "").strip()
        if not clause_id:
            continue
        root = _clause_root(clause_id)
        if not root:
            continue
        by_root.setdefault(root, []).append(_citation_text_for_match(citation=c, max_len=500))
    return {root: "\n".join(parts) for root, parts in by_root.items()}


def _rank_clause_roots_for_listing(question: str, citations: list[dict[str, Any]]) -> list[str]:
    by_root_scores: dict[str, list[float]] = {}
    by_root_clause_ids: dict[str, set[str]] = {}
    for c in citations:
        clause_id = str(c.get("clause_id") or "").strip()
        if not clause_id:
            continue
        root = _clause_root(clause_id)
        if not root:
            continue
        by_root_scores.setdefault(root, []).append(_citation_clause_weight(question=question, citation=c, listing_query=True))
        by_root_clause_ids.setdefault(root, set()).add(clause_id)
    if not by_root_scores:
        return []

    root_texts = _collect_root_texts(citations)
    install_listing = _question_has_install_intent(question) and not _question_has_vacuum_terms(question)
    root_scores: dict[str, float] = {}
    for root, vals in by_root_scores.items():
        ordered = sorted(vals, reverse=True)
        score = ordered[0]
        if len(ordered) > 1:
            score += 0.35 * ordered[1]
        score += min(1.6, 0.18 * len(by_root_clause_ids.get(root, set())))
        if install_listing:
            agg = str(root_texts.get(root) or "")
            install_hits = agg.count("安装")
            vac_hits = sum(agg.count(token) for token in _VACUUM_HINTS)
            text_len = max(1, len(agg))
            score += min(7.0, install_hits * 0.3)
            score += min(5.0, (install_hits * 40.0) / text_len)
            score -= min(8.0, vac_hits * 0.2)
        root_scores[root] = score

    major_scores: dict[str, float] = {}
    for root, score in root_scores.items():
        major = _clause_major(root)
        if not major:
            continue
        major_scores[major] = float(major_scores.get(major) or 0.0) + max(0.0, float(score))
    dominant_major = max(major_scores.items(), key=lambda x: x[1])[0] if major_scores else ""
    ranked_roots = [r for r in root_scores if (not dominant_major or _clause_major(r) == dominant_major)]

    return sorted(
        ranked_roots,
        key=lambda r: (
            -root_scores[r],
            -len(by_root_clause_ids.get(r, set())),
            r,
        ),
    )


def _build_fixed_clause_answer(question: str, citations: list[dict[str, Any]]) -> str | None:
    if not _should_use_fixed_clause_format(question=question, citations=citations):
        return None

    explicit_clause_ids = _extract_clause_ids_from_question(question) if _should_trust_explicit_clause_ids(question) else []
    listing_query = _is_listing_clause_query(question)
    if explicit_clause_ids:
        roots = list(dict.fromkeys(_clause_root(x) for x in explicit_clause_ids if _clause_root(x)))
    elif listing_query:
        roots, _ = _pick_target_clauses(question=question, citations=citations)
    else:
        dominant_clause = _pick_dominant_clause_id(question=question, citations=citations)
        roots = [_clause_root(dominant_clause)] if dominant_clause else []

    scoped = (
        [c for c in citations if any(_same_clause_family(str(c.get("clause_id") or ""), root) for root in roots)]
        if roots
        else list(citations)
    )

    explanation = [c for c in scoped if _is_explanation_citation(c)]
    clauses = [c for c in scoped if not _is_explanation_citation(c)]
    if not clauses and not explanation:
        explanation = [c for c in citations if _is_explanation_citation(c)]
        clauses = [c for c in citations if not _is_explanation_citation(c)]
        if not clauses and not explanation:
            return None

    clauses_primary = [c for c in clauses if str(c.get("source_type") or "").strip().lower() not in {"section_summary"}]
    clause_limit = 6 if listing_query else 5
    explanation_limit = 4 if not listing_query else 5
    if listing_query and roots:
        ordered_candidates: list[dict[str, Any]] = []
        used_keys: set[tuple[str, int | None, int | None, str, str, str]] = set()
        for root in roots:
            family = [c for c in clauses if _same_clause_family(str(c.get("clause_id") or ""), root)]
            if not family:
                continue
            preferred = next(
                (
                    c
                    for c in family
                    if str(c.get("source_type") or "").strip().lower() not in {"section_summary"}
                ),
                None,
            )
            if preferred is None:
                preferred = family[0]
            key = _citation_key(preferred)
            if key in used_keys:
                continue
            used_keys.add(key)
            ordered_candidates.append(preferred)
        for c in (clauses_primary or clauses or citations):
            key = _citation_key(c)
            if key in used_keys:
                continue
            used_keys.add(key)
            ordered_candidates.append(c)
            if len(ordered_candidates) >= clause_limit:
                break
        clause_lines = _pick_section_lines(
            ordered_candidates,
            limit=clause_limit,
            concise=True,
            max_len=int(os.getenv("CHAT_CLAUSE_TEMPLATE_LINE_MAX_CHARS_LISTING", "320")),
        )
    else:
        clause_lines = _pick_section_lines(clauses_primary or clauses or citations, limit=clause_limit)
    explanation_lines = _pick_section_lines(
        explanation,
        limit=explanation_limit,
        concise=listing_query,
        max_len=int(os.getenv("CHAT_CLAUSE_TEMPLATE_LINE_MAX_CHARS_LISTING", "320")) if listing_query else 520,
    )

    lines: list[str] = ["条文规定："]
    for idx, line in enumerate(clause_lines, start=1):
        lines.append(f"{idx}. {line}")
    if explanation_lines:
        lines.append("")
        lines.append("条文说明：")
        for idx, line in enumerate(explanation_lines, start=1):
            lines.append(f"{idx}. {line}")
    return "\n".join(lines).strip()


def chat_with_citations(
    question: str,
    repo: SearchRepo,
    entity_index: Any,
    runtime_config: dict[str, Any] | None = None,
    search_filter: dict[str, Any] | None = None,
    mode: str = "qa",
) -> dict[str, Any]:
    top_k = max(5, int(os.getenv("CHAT_SEARCH_TOP_K", "16")))
    if _is_listing_clause_query(question):
        top_k = max(top_k, int(os.getenv("CHAT_SEARCH_TOP_K_LISTING", "48")))
    search_res = hybrid_search(
        question=question,
        repo=repo,
        entity_index=entity_index,
        top_k=top_k,
        runtime_config=runtime_config,
        search_filter=search_filter,
    )
    citations = _dedupe_citations(search_res["citations"])
    selected_mode = str(mode or "qa").strip().lower()
    if selected_mode == "constraint":
        constraints = _build_constraint_items(citations)
        constraints_for_model = _build_constraint_model_items(constraints)
        answer = _build_constraint_summary(question=question, constraints=constraints)
        return {
            "answer": answer,
            "mode": "constraint",
            "constraints": constraints,
            "constraints_for_model": constraints_for_model,
            "citations": citations,
            "expandable_evidence": _build_expandable_evidence(citations),
            "llm": {"provider": "local", "model": "constraint-summary"},
        }

    if citations:
        template_citations = _attach_clause_family_siblings(question=question, citations=citations, repo=repo)
        fixed_answer = _build_fixed_clause_answer(question=question, citations=template_citations)
        if fixed_answer:
            return {
                "answer": fixed_answer,
                "mode": "qa",
                "citations": template_citations,
                "expandable_evidence": _build_expandable_evidence(template_citations),
                "llm": {"provider": "local", "model": "clause-template-v1"},
            }

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
        "mode": "qa",
        "citations": citations,
        "expandable_evidence": _build_expandable_evidence(citations),
        "llm": {"provider": llm_res["provider"], "model": llm_res["model"]},
    }
