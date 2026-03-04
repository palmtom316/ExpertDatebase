import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.services import chat_orchestrator  # noqa: E402
from app.services.chat_orchestrator import (  # noqa: E402
    _compact_clause_text,
    _pick_best_evidence_text,
    chat_with_citations,
)
from app.services.search_service import _extract_query_terms  # noqa: E402


class _DummyEntityIndex:
    def match_names(self, kind: str, question: str) -> list[str]:  # noqa: ARG002
        return []

    def get_id(self, kind: str, name: str) -> str | None:  # noqa: ARG002
        return None


def test_extract_query_terms_reduces_cn_noise_for_listing_query() -> None:
    terms = _extract_query_terms("变压器的安装有哪些规定")
    assert "安装" in terms
    assert "变压器" in terms
    assert "变压器的安装有哪些规定" not in terms
    assert "有哪些" not in terms
    assert "装有" not in terms
    assert "些规" not in terms


def test_pick_target_clauses_prefers_install_roots(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAT_CLAUSE_TEMPLATE_LISTING_FAMILIES", "3")
    citations = [
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 57,
            "page_end": 57,
            "excerpt": "4.9.6 在抽真空时，应采取防倒灌措施。",
            "chunk_text": "4.9.6 在抽真空时，应采取防倒灌措施。",
            "source_type": "text",
            "clause_id": "4.9.6",
        },
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 25,
            "page_end": 25,
            "excerpt": "章节：4.6内部安装、连接 摘要：4.6内部安装、连接。",
            "chunk_text": "章节：4.6内部安装、连接 摘要：4.6内部安装、连接。",
            "source_type": "section_summary",
            "clause_id": "4.6",
        },
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 52,
            "page_end": 52,
            "excerpt": "章节：4.8本体及附件安装 摘要：4.8本体及附件安装。",
            "chunk_text": "章节：4.8本体及附件安装 摘要：4.8本体及附件安装。",
            "source_type": "section_summary",
            "clause_id": "4.8",
        },
    ]
    targets, family_mode = chat_orchestrator._pick_target_clauses(  # type: ignore[attr-defined]
        question="变压器的安装有哪些规定",
        citations=citations,
    )
    assert family_mode is True
    assert "4.6" in targets
    assert "4.8" in targets
    assert targets.index("4.6") < targets.index("4.9")
    assert targets.index("4.8") < targets.index("4.9")


def test_chat_listing_query_keeps_multiple_clause_families(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_search(*args, **kwargs):  # noqa: ARG001
        return {
            "citations": [
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 57,
                    "page_end": 57,
                    "excerpt": "4.9.6 在抽真空时，应采取防倒灌措施。",
                    "chunk_text": "4.9.6 在抽真空时，应采取防倒灌措施。",
                    "source_type": "text",
                    "clause_id": "4.9.6",
                },
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 52,
                    "page_end": 52,
                    "excerpt": "4.8.4 对冷却装置的安装作了下列要求。",
                    "chunk_text": "4.8.4 对冷却装置的安装作了下列要求。",
                    "source_type": "text",
                    "clause_id": "4.8.4",
                },
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 25,
                    "page_end": 25,
                    "excerpt": "4.6.1 变压器的内部安装、连接，应按产品说明执行。",
                    "chunk_text": "4.6.1 变压器的内部安装、连接，应按产品说明执行。",
                    "source_type": "text",
                    "clause_id": "4.6.1",
                },
            ]
        }

    monkeypatch.setattr(chat_orchestrator, "hybrid_search", fake_search)
    result = chat_with_citations(
        question="变压器的安装有哪些规定",
        repo=None,
        entity_index=_DummyEntityIndex(),
    )
    assert result["llm"]["model"] == "clause-template-v1"
    assert "4.8.4" in result["answer"]
    assert "4.6.1" in result["answer"]


def test_chat_listing_query_keeps_section_summary_root_line(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_search(*args, **kwargs):  # noqa: ARG001
        return {
            "citations": [
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 25,
                    "page_end": 25,
                    "excerpt": "章节：4.6内部安装、连接 摘要：4.6内部安装、连接。",
                    "chunk_text": "章节：4.6内部安装、连接 摘要：4.6内部安装、连接。",
                    "source_type": "section_summary",
                    "clause_id": "4.6",
                },
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 52,
                    "page_end": 52,
                    "excerpt": "4.8.4 对冷却装置的安装作了下列要求。",
                    "chunk_text": "4.8.4 对冷却装置的安装作了下列要求。",
                    "source_type": "text",
                    "clause_id": "4.8.4",
                },
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 16,
                    "page_end": 16,
                    "excerpt": "4.1.9 本体就位应符合下列规定。",
                    "chunk_text": "4.1.9 本体就位应符合下列规定。",
                    "source_type": "text",
                    "clause_id": "4.1.9",
                },
            ]
        }

    monkeypatch.setenv("CHAT_CLAUSE_TEMPLATE_LISTING_FAMILIES", "3")
    monkeypatch.setattr(chat_orchestrator, "hybrid_search", fake_search)
    result = chat_with_citations(
        question="变压器的安装有哪些规定",
        repo=None,
        entity_index=_DummyEntityIndex(),
    )
    assert "4.6内部安装、连接" in result["answer"]


def test_chat_listing_query_uses_listing_top_k(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, int] = {}

    def fake_search(*args, **kwargs):  # noqa: ARG001
        observed["top_k"] = int(kwargs.get("top_k") or 0)
        return {"citations": []}

    monkeypatch.setenv("CHAT_SEARCH_TOP_K", "16")
    monkeypatch.setenv("CHAT_SEARCH_TOP_K_LISTING", "48")
    monkeypatch.setattr(chat_orchestrator, "hybrid_search", fake_search)
    _ = chat_with_citations(
        question="变压器的安装有哪些规定",
        repo=None,
        entity_index=_DummyEntityIndex(),
    )
    assert observed["top_k"] == 48


def test_pick_best_evidence_text_removes_ocr_text_tokens() -> None:
    citation = {
        "excerpt": "",
        "chunk_text": "4.8.4对冷却装置的安装作了下列要求：: 46. text 6 油冷却器现场配制的外接管路应清理干净。",
    }
    text = _pick_best_evidence_text(citation, max_len=240)
    assert "text 6" not in text.lower()
    assert "4.8.4" in text


def test_pick_best_evidence_text_dedupes_repeated_sentence() -> None:
    citation = {
        "excerpt": "",
        "chunk_text": "4.1装卸、运输与就位。4.1装卸、运输与就位。现场检查应符合要求。",
    }
    text = _pick_best_evidence_text(citation, max_len=240)
    assert text.count("4.1装卸、运输与就位") == 1


def test_pick_best_evidence_text_trims_repeated_section_summary() -> None:
    citation = {
        "source_type": "section_summary",
        "excerpt": "",
        "chunk_text": (
            "章节：4.6内部安装、连接 摘要：4.6内部安装、连接；4.6.1应执行产品说明。"
            "章节：4.6内部安装、连接 摘要：4.6内部安装、连接；4.6.1应执行产品说明。"
        ),
    }
    text = _pick_best_evidence_text(citation, max_len=360)
    assert text.count("章节：4.6内部安装、连接") == 1


def test_compact_clause_text_limits_sentences_and_length() -> None:
    text = (
        "4.8.4对冷却装置的安装作了下列要求。冷却装置安装前应按制造厂规定进行密封试验。"
        "外接管路应彻底除锈并清理。油位表应指示正确。"
    )
    compact = _compact_clause_text(text, max_chars=60, max_sentences=2)
    assert compact.count("。") <= 2
    assert len(compact) <= 61
