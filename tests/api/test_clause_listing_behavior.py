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


def test_extract_listing_focus_terms_keeps_subject_keyword() -> None:
    focus = chat_orchestrator._extract_listing_focus_terms("变压器安装有哪些规定")  # type: ignore[attr-defined]
    assert "变压器" in focus
    assert "安装" not in focus


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
    assert "4.9" not in targets


def test_pick_target_clauses_prefers_focus_root_for_transformer_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAT_CLAUSE_TEMPLATE_LISTING_FAMILIES", "3")
    citations = [
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 59,
            "page_end": 59,
            "excerpt": "11.2 电容器的安装。",
            "chunk_text": "11.2 电容器的安装。",
            "source_type": "text",
            "clause_id": "11.2",
        },
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 15,
            "page_end": 16,
            "excerpt": "3.0.7 与高压电器安装有关的建筑工程施工应符合下列规定。",
            "chunk_text": "3.0.7 与高压电器安装有关的建筑工程施工应符合下列规定。",
            "source_type": "text",
            "clause_id": "3.0.7",
        },
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 16,
            "page_end": 16,
            "excerpt": "3.0.9 ... 应符合《变压器、高压电器和套管的接线端子》GB5273。",
            "chunk_text": "3.0.9 ... 应符合《变压器、高压电器和套管的接线端子》GB5273。",
            "source_type": "text",
            "clause_id": "3.0.9",
        },
    ]
    targets, family_mode = chat_orchestrator._pick_target_clauses(  # type: ignore[attr-defined]
        question="变压器安装有哪些规定",
        citations=citations,
    )
    assert family_mode is True
    assert targets
    assert targets[0] == "3.0"


def test_pick_target_clauses_skips_preface_like_roots_for_install_listing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAT_CLAUSE_TEMPLATE_LISTING_FAMILIES", "3")
    citations = [
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 38,
            "page_end": 38,
            "excerpt": "A.0.2 充气运输的变压器及电抗器应符合下列规定。",
            "chunk_text": "A.0.2 充气运输的变压器及电抗器应符合下列规定。",
            "source_type": "text",
            "clause_id": "0.2",
        },
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 3,
            "page_end": 3,
            "excerpt": "统一书号 494 定价：13.00元。",
            "chunk_text": "统一书号 494 定价：13.00元。",
            "source_type": "text",
            "clause_id": "13.00",
        },
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 13,
            "page_end": 14,
            "excerpt": "3.0.6 与安装有关的建筑工程施工应符合下列规定。",
            "chunk_text": "3.0.6 与安装有关的建筑工程施工应符合下列规定。",
            "source_type": "text",
            "clause_id": "3.0.6",
        },
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 27,
            "page_end": 27,
            "excerpt": "4.8.4 冷却装置的安装应符合下列规定。",
            "chunk_text": "4.8.4 冷却装置的安装应符合下列规定。",
            "source_type": "text",
            "clause_id": "4.8.4",
        },
    ]
    targets, family_mode = chat_orchestrator._pick_target_clauses(  # type: ignore[attr-defined]
        question="变压器安装有哪些规定",
        citations=citations,
    )
    assert family_mode is True
    assert "3.0" in targets
    assert "4.8" in targets
    assert "0.2" not in targets
    assert "13.00" not in targets


def test_pick_target_clauses_transformer_install_limits_noise_roots(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAT_CLAUSE_TEMPLATE_LISTING_FAMILIES", "3")
    citations = [
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 13,
            "page_end": 14,
            "excerpt": "3.0.6 与变压器安装有关的建筑工程施工应符合下列规定。",
            "chunk_text": "3.0.6 与变压器安装有关的建筑工程施工应符合下列规定。",
            "source_type": "text",
            "clause_id": "3.0.6",
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
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 32,
            "page_end": 32,
            "excerpt": "4.11.3 对变压器进行密封性试验。",
            "chunk_text": "4.11.3 对变压器进行密封性试验。",
            "source_type": "text",
            "clause_id": "4.11.3",
        },
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 27,
            "page_end": 27,
            "excerpt": "4.8.4 冷却装置的安装应符合下列规定。",
            "chunk_text": "4.8.4 冷却装置的安装应符合下列规定。",
            "source_type": "text",
            "clause_id": "4.8.4",
        },
    ]
    targets, family_mode = chat_orchestrator._pick_target_clauses(  # type: ignore[attr-defined]
        question="变压器安装有哪些规定",
        citations=citations,
    )
    assert family_mode is True
    assert "3.0" in targets
    assert "4.8" in targets
    assert "4.11" not in targets


def test_select_template_output_citations_filters_listing_noise() -> None:
    citations = [
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 3,
            "page_end": 3,
            "excerpt": "统一书号 494 定价：13.00元。",
            "chunk_text": "统一书号 494 定价：13.00元。",
            "source_type": "text",
            "clause_id": "13.00",
        },
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 38,
            "page_end": 38,
            "excerpt": "A.0.2 充气运输的变压器及电抗器应符合下列规定。",
            "chunk_text": "A.0.2 充气运输的变压器及电抗器应符合下列规定。",
            "source_type": "text",
            "clause_id": "0.2",
        },
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 13,
            "page_end": 14,
            "excerpt": "3.0.6 与安装有关的建筑工程施工应符合下列规定。",
            "chunk_text": "3.0.6 与安装有关的建筑工程施工应符合下列规定。",
            "source_type": "text",
            "clause_id": "3.0.6",
        },
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 27,
            "page_end": 27,
            "excerpt": "4.8.4 冷却装置的安装应符合下列规定。",
            "chunk_text": "4.8.4 冷却装置的安装应符合下列规定。",
            "source_type": "text",
            "clause_id": "4.8.4",
        },
    ]
    out = chat_orchestrator._select_template_output_citations(  # type: ignore[attr-defined]
        question="变压器安装有哪些规定",
        citations=citations,
    )
    out_clause_ids = [str(x.get("clause_id") or "") for x in out]
    assert "3.0.6" in out_clause_ids
    assert "4.8.4" in out_clause_ids
    assert "13.00" not in out_clause_ids


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


def test_attach_clause_family_siblings_expands_family_by_keyword_when_listing() -> None:
    class _Repo:
        def fetch_by_filter(self, filter_json=None, limit=20):  # noqa: ARG002
            return []

        def keyword_search(self, query_text, filter_json=None, limit=20):  # noqa: ARG002
            if query_text != "3.0":
                return []
            return [
                {
                    "id": "ck_306",
                    "score": 1.0,
                    "payload": {
                        "doc_name": "spec.pdf",
                        "doc_id": "doc_spec",
                        "page_start": 15,
                        "page_end": 15,
                        "source_type": "text",
                        "chunk_text": "3.0.6 设备基础应符合安装要求。",
                        "excerpt": "3.0.6 设备基础应符合安装要求。",
                        "clause_id": "3.0.6",
                    },
                },
                {
                    "id": "ck_307",
                    "score": 0.9,
                    "payload": {
                        "doc_name": "spec.pdf",
                        "doc_id": "doc_spec",
                        "page_start": 15,
                        "page_end": 16,
                        "source_type": "text",
                        "chunk_text": "3.0.7 与安装有关的建筑工程施工应符合规定。",
                        "excerpt": "3.0.7 与安装有关的建筑工程施工应符合规定。",
                        "clause_id": "3.0.7",
                    },
                },
            ]

    citations = [
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 15,
            "page_end": 16,
            "excerpt": "3.0.7 与安装有关的建筑工程施工应符合规定。",
            "chunk_text": "3.0.7 与安装有关的建筑工程施工应符合规定。",
            "source_type": "text",
            "clause_id": "3.0.7",
        }
    ]
    out = chat_orchestrator._attach_clause_family_siblings(  # type: ignore[attr-defined]
        question="变压器安装有哪些规定",
        citations=citations,
        repo=_Repo(),
    )
    clause_ids = [str(item.get("clause_id") or "") for item in out]
    assert "3.0.6" in clause_ids
    assert "3.0.7" in clause_ids


def test_attach_clause_family_siblings_merges_section_hits_when_keyword_partial() -> None:
    class _Repo:
        def fetch_by_filter(self, filter_json=None, limit=20):  # noqa: ARG002
            must = (filter_json or {}).get("must") or []
            has_section = any(
                isinstance(item, dict)
                and item.get("key") == "section_no"
                and isinstance(item.get("match"), dict)
                and item["match"].get("value") == "3.0"
                for item in must
            )
            if not has_section:
                return []
            return [
                {
                    "id": "ck_306",
                    "score": 1.0,
                    "payload": {
                        "doc_name": "spec.pdf",
                        "doc_id": "doc_spec",
                        "page_start": 15,
                        "page_end": 15,
                        "source_type": "text",
                        "chunk_text": "3.0.6 施工前应编制施工方案。",
                        "excerpt": "3.0.6 施工前应编制施工方案。",
                        "clause_id": "3.0.6",
                    },
                }
            ]

        def keyword_search(self, query_text, filter_json=None, limit=20):  # noqa: ARG002
            if query_text != "3.0":
                return []
            return [
                {
                    "id": "ck_307",
                    "score": 1.0,
                    "payload": {
                        "doc_name": "spec.pdf",
                        "doc_id": "doc_spec",
                        "page_start": 15,
                        "page_end": 16,
                        "source_type": "text",
                        "chunk_text": "3.0.7 与安装有关的建筑工程施工应符合规定。",
                        "excerpt": "3.0.7 与安装有关的建筑工程施工应符合规定。",
                        "clause_id": "3.0.7",
                    },
                }
            ]

    citations = [
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 15,
            "page_end": 16,
            "excerpt": "3.0.7 与安装有关的建筑工程施工应符合规定。",
            "chunk_text": "3.0.7 与安装有关的建筑工程施工应符合规定。",
            "source_type": "text",
            "clause_id": "3.0.7",
        }
    ]
    out = chat_orchestrator._attach_clause_family_siblings(  # type: ignore[attr-defined]
        question="变压器安装有哪些规定",
        citations=citations,
        repo=_Repo(),
    )
    clause_ids = [str(item.get("clause_id") or "") for item in out]
    assert "3.0.6" in clause_ids
    assert "3.0.7" in clause_ids


def test_attach_clause_family_siblings_backfills_required_transformer_clauses() -> None:
    class _Repo:
        def fetch_by_filter(self, filter_json=None, limit=20):  # noqa: ARG002
            must = (filter_json or {}).get("must") or []
            clause_any = next(
                (
                    item.get("match", {}).get("any")
                    for item in must
                    if isinstance(item, dict)
                    and item.get("key") == "clause_id"
                    and isinstance(item.get("match"), dict)
                    and item.get("match", {}).get("any")
                ),
                None,
            )
            if clause_any and "3.0.7" in clause_any:
                return [
                    {
                        "id": "ck_307",
                        "score": 1.0,
                        "payload": {
                            "doc_name": "spec.pdf",
                            "doc_id": "doc_spec",
                            "page_start": 14,
                            "page_end": 14,
                            "source_type": "text",
                            "chunk_text": "3.0.7 设备安装用紧固件应符合规定。",
                            "excerpt": "3.0.7 设备安装用紧固件应符合规定。",
                            "clause_id": "3.0.7",
                        },
                    }
                ]
            return []

        def keyword_search(self, query_text, filter_json=None, limit=20):  # noqa: ARG002
            if query_text != "3.0":
                return []
            return [
                {
                    "id": "ck_306",
                    "score": 1.0,
                    "payload": {
                        "doc_name": "spec.pdf",
                        "doc_id": "doc_spec",
                        "page_start": 13,
                        "page_end": 14,
                        "source_type": "text",
                        "chunk_text": "3.0.6 与安装有关的建筑工程施工应符合下列规定。",
                        "excerpt": "3.0.6 与安装有关的建筑工程施工应符合下列规定。",
                        "clause_id": "3.0.6",
                    },
                }
            ]

    citations = [
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 13,
            "page_end": 14,
            "excerpt": "3.0.6 与安装有关的建筑工程施工应符合下列规定。",
            "chunk_text": "3.0.6 与安装有关的建筑工程施工应符合下列规定。",
            "source_type": "text",
            "clause_id": "3.0.6",
        }
    ]
    out = chat_orchestrator._attach_clause_family_siblings(  # type: ignore[attr-defined]
        question="变压器安装有哪些规定",
        citations=citations,
        repo=_Repo(),
    )
    clause_ids = [str(item.get("clause_id") or "") for item in out]
    assert "3.0.6" in clause_ids
    assert "3.0.7" in clause_ids


def test_build_fixed_clause_answer_listing_keeps_previous_adjacent_clause() -> None:
    citations = [
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 15,
            "page_end": 16,
            "excerpt": "3.0.7 与安装有关的建筑工程施工应符合下列规定。",
            "chunk_text": "3.0.7 与安装有关的建筑工程施工应符合下列规定。",
            "source_type": "text",
            "clause_id": "3.0.7",
        },
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 16,
            "page_end": 16,
            "excerpt": "3.0.9 设备安装用紧固件应符合《变压器、高压电器和套管的接线端子》标准。",
            "chunk_text": "3.0.9 设备安装用紧固件应符合《变压器、高压电器和套管的接线端子》标准。",
            "source_type": "text",
            "clause_id": "3.0.9",
        },
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 15,
            "page_end": 15,
            "excerpt": "3.0.1 高压电器安装应按设计执行。",
            "chunk_text": "3.0.1 高压电器安装应按设计执行。",
            "source_type": "text",
            "clause_id": "3.0.1",
        },
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 16,
            "page_end": 16,
            "excerpt": "3.0.10 高压电器接地应符合标准。",
            "chunk_text": "3.0.10 高压电器接地应符合标准。",
            "source_type": "text",
            "clause_id": "3.0.10",
        },
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 16,
            "page_end": 16,
            "excerpt": "3.0.11 安装验收应符合技术文件。",
            "chunk_text": "3.0.11 安装验收应符合技术文件。",
            "source_type": "text",
            "clause_id": "3.0.11",
        },
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 16,
            "page_end": 16,
            "excerpt": "3.0.12 安装过程记录应完整。",
            "chunk_text": "3.0.12 安装过程记录应完整。",
            "source_type": "text",
            "clause_id": "3.0.12",
        },
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 16,
            "page_end": 16,
            "excerpt": "3.0.13 安装完成后应进行交接。",
            "chunk_text": "3.0.13 安装完成后应进行交接。",
            "source_type": "text",
            "clause_id": "3.0.13",
        },
        {
            "doc_name": "spec.pdf",
            "doc_id": "doc_spec",
            "page_start": 15,
            "page_end": 15,
            "excerpt": "3.0.6 施工前应编制施工方案。",
            "chunk_text": "3.0.6 施工前应编制施工方案。",
            "source_type": "text",
            "clause_id": "3.0.6",
        },
    ]

    answer = chat_orchestrator._build_fixed_clause_answer(  # type: ignore[attr-defined]
        question="变压器安装有哪些规定",
        citations=citations,
    )
    assert answer is not None
    assert "3.0.7" in answer
    assert "3.0.6" in answer


def test_chat_listing_query_prefers_focus_family_and_avoids_capacitor_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_search(*args, **kwargs):  # noqa: ARG001
        return {
            "citations": [
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 59,
                    "page_end": 59,
                    "excerpt": "11.2 电容器的安装应满足本章规定。",
                    "chunk_text": "11.2 电容器的安装应满足本章规定。",
                    "source_type": "text",
                    "clause_id": "11.2",
                },
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 61,
                    "page_end": 61,
                    "excerpt": "11.3 耦合电容器的安装应满足本章规定。",
                    "chunk_text": "11.3 耦合电容器的安装应满足本章规定。",
                    "source_type": "text",
                    "clause_id": "11.3",
                },
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 16,
                    "page_end": 16,
                    "excerpt": "3.0.9 设备安装用紧固件应符合《变压器、高压电器和套管的接线端子》GB5273。",
                    "chunk_text": "3.0.9 设备安装用紧固件应符合《变压器、高压电器和套管的接线端子》GB5273。",
                    "source_type": "text",
                    "clause_id": "3.0.9",
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
    assert "3.0.9" in result["answer"]
    assert "电容器" not in result["answer"]


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
