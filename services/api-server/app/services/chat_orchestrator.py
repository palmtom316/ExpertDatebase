"""Chat orchestration with mandatory citations."""

from __future__ import annotations

from typing import Any

from app.services.llm_router import LLMRouter
from app.services.search_service import SearchRepo, hybrid_search


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


def chat_with_citations(
    question: str,
    repo: SearchRepo,
    entity_index: Any,
) -> dict[str, Any]:
    search_res = hybrid_search(question=question, repo=repo, entity_index=entity_index, top_k=5)
    citations = search_res["citations"]

    router = LLMRouter()
    llm_res = router.route_and_generate(task_type="qa_generate", prompt=question)

    if not citations:
        answer = "未检索到可用证据，无法给出有引用支撑的回答。"
    else:
        answer = llm_res["text"]

    return {
        "answer": answer,
        "citations": citations,
        "expandable_evidence": _build_expandable_evidence(citations),
        "llm": {"provider": llm_res["provider"], "model": llm_res["model"]},
    }
