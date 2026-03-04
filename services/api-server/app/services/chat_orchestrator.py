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
    raw_excerpt = str(citation.get("excerpt") or "")
    raw_chunk = str(citation.get("chunk_text") or "")
    excerpt = _clean_text(raw_excerpt, max_len=max_len)
    chunk_text = _clean_text(raw_chunk, max_len=max_len)
    chunk_readable = _readable_ratio(chunk_text) >= 0.55
    excerpt_readable = _readable_ratio(excerpt) >= 0.55
    # Prefer chunk text when stored excerpt is a short snapshot.
    if chunk_readable and len(raw_chunk) > len(raw_excerpt) + 30:
        return chunk_text
    if excerpt_readable:
        return excerpt
    if chunk_readable:
        return chunk_text
    return excerpt or chunk_text


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


def _build_constraint_items(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for c in citations:
        excerpt = _pick_best_evidence_text(c, max_len=240)
        if not excerpt:
            continue
        items.append(
            {
                "doc_name": str(c.get("doc_name") or "").strip(),
                "page_start": c.get("page_start"),
                "page_end": c.get("page_end"),
                "clause_id": str(c.get("clause_id") or "").strip(),
                "is_mandatory": bool(c.get("is_mandatory")),
                "risk_level": _constraint_risk_level(c),
                "evidence": excerpt,
            }
        )
    return items


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


def _should_use_fixed_clause_format(question: str, citations: list[dict[str, Any]]) -> bool:
    if not citations:
        return False
    has_clause = any(str(c.get("clause_id") or "").strip() for c in citations)
    if not has_clause:
        return False
    q = str(question or "").strip()
    if not q:
        return False
    if re.search(r"(?<!\d)\d{1,2}(?:\.\d+){1,4}(?:\([0-9A-Za-z]+\))?(?!\d)", q):
        return True
    return any(token in q for token in ["条文", "规定", "服从", "应符合"])


def _format_clause_line(citation: dict[str, Any], max_len: int = 520) -> str:
    text = _pick_best_evidence_text(citation, max_len=max_len)
    if not text:
        text = "（该页未提取到可读文本）"
    doc_name = str(citation.get("doc_name") or "unknown").strip()
    page = citation.get("page_start")
    page_text = f"p.{page}" if page is not None else "p.-"
    return f"{text}（{doc_name} {page_text}）"


def _pick_section_lines(citations: list[dict[str, Any]], limit: int = 3) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for c in citations:
        line = _format_clause_line(citation=c)
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


def _attach_clause_family_siblings(question: str, citations: list[dict[str, Any]], repo: SearchRepo) -> list[dict[str, Any]]:
    if not citations or not _env_enabled("CHAT_CLAUSE_TEMPLATE_ATTACH_SIBLINGS", default=True):
        return citations
    if not _should_use_fixed_clause_format(question=question, citations=citations):
        return citations

    dominant_clause = _pick_dominant_clause_id(question=question, citations=citations)
    if not dominant_clause:
        return citations

    fetch_fn = getattr(repo, "fetch_by_filter", None)
    if not callable(fetch_fn):
        return citations

    scoped_doc_ids = [
        str(c.get("doc_id") or "").strip()
        for c in citations
        if _same_clause_family(str(c.get("clause_id") or ""), dominant_clause)
    ]
    primary_doc_id = next((x for x in scoped_doc_ids if x), "")

    must = [
        {"key": "clause_id", "match": {"value": dominant_clause}},
        {"key": "source_type", "match": {"any": ["text", "explanation", "section_summary"]}},
    ]
    if primary_doc_id:
        must.append({"key": "doc_id", "match": {"value": primary_doc_id}})
    sibling_filter = {"must": must}
    sibling_limit = max(4, int(os.getenv("CHAT_CLAUSE_TEMPLATE_SIBLING_LIMIT", "12")))
    try:
        sibling_hits = fetch_fn(filter_json=sibling_filter, limit=sibling_limit) or []
    except Exception:  # noqa: BLE001
        sibling_hits = []

    out: list[dict[str, Any]] = []
    seen_index: dict[tuple[str, int | None, int | None, str, str, str], int] = {}
    for c in citations:
        key = _citation_key(c)
        if key in seen_index:
            continue
        seen_index[key] = len(out)
        out.append(c)

    for hit in sibling_hits:
        payload = (hit or {}).get("payload") if isinstance(hit, dict) else None
        if not isinstance(payload, dict):
            continue
        c = _repo_payload_to_citation(payload=payload)
        key = _citation_key(c)
        if key in seen_index:
            idx = seen_index[key]
            prev = out[idx]
            prev["excerpt"] = _merge_text(str(prev.get("excerpt") or ""), str(c.get("excerpt") or ""), max_len=1000)
            prev["chunk_text"] = _merge_text(str(prev.get("chunk_text") or ""), str(c.get("chunk_text") or ""), max_len=4000)
            prev["merged_count"] = int(prev.get("merged_count") or 1) + 1
            continue
        seen_index[key] = len(out)
        out.append(c)

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


def _extract_question_match_terms(question: str) -> list[str]:
    q = str(question or "").lower()
    q = re.sub(r"(?<!\d)\d{1,2}(?:\.\d+){1,4}(?:\([0-9A-Za-z]+\))?(?!\d)", " ", q)
    q = re.sub(r"(回复|回答|查询到|没查询到|没有查询到|为什么|还是|但是|却)", " ", q)
    q = re.sub(r"\s+", "", q)
    terms: list[str] = []
    runs = re.findall(r"[\u4e00-\u9fff]{2,24}", q)
    for run in runs:
        terms.append(run)
        run_len = len(run)
        for n in (2, 3, 4):
            if run_len < n:
                continue
            for i in range(0, run_len - n + 1):
                terms.append(run[i : i + n])
    out: list[str] = []
    seen: set[str] = set()
    for t in terms:
        x = t.strip()
        if len(x) < 2 or x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


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


def _pick_dominant_clause_id(question: str, citations: list[dict[str, Any]]) -> str:
    scores: dict[str, float] = {}
    order: list[str] = []
    for c in citations:
        clause_id = str(c.get("clause_id") or "").strip()
        if not clause_id:
            continue
        if clause_id not in scores:
            scores[clause_id] = 0.0
            order.append(clause_id)
        source_type = str(c.get("source_type") or "").strip().lower()
        weight = 1.0
        if not _is_explanation_citation(c):
            weight += 1.0
        if source_type == "text":
            weight += 0.6
        if source_type == "section_summary":
            weight -= 0.4
        weight += min(0.6, _clause_depth(clause_id) * 0.2)
        weight += min(12.0, _question_to_citation_relevance(question=question, citation=c))
        scores[clause_id] += weight
    if not scores:
        return ""
    best = order[0]
    best_score = scores[best]
    for cid in order[1:]:
        score = scores[cid]
        if score > best_score:
            best = cid
            best_score = score
            continue
        if score == best_score and _clause_depth(cid) > _clause_depth(best):
            best = cid
            best_score = score
    return best


def _build_fixed_clause_answer(question: str, citations: list[dict[str, Any]]) -> str | None:
    if not _should_use_fixed_clause_format(question=question, citations=citations):
        return None

    dominant_clause = _pick_dominant_clause_id(question=question, citations=citations)
    scoped = (
        [c for c in citations if _same_clause_family(str(c.get("clause_id") or ""), dominant_clause)]
        if dominant_clause
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
    clause_lines = _pick_section_lines(clauses_primary or clauses or citations, limit=5)
    explanation_lines = _pick_section_lines(explanation, limit=4)

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
        answer = _build_constraint_summary(question=question, constraints=constraints)
        return {
            "answer": answer,
            "mode": "constraint",
            "constraints": constraints,
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
