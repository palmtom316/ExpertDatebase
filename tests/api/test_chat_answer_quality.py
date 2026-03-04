import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.services import chat_orchestrator  # noqa: E402
from app.services.chat_orchestrator import chat_with_citations  # noqa: E402


class _DummyEntityIndex:
    def match_names(self, kind: str, question: str) -> list[str]:
        return []

    def get_id(self, kind: str, name: str) -> str | None:
        return None


def test_chat_dedupes_citations_by_doc_and_page(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_search(*args, **kwargs):
        return {
            "citations": [
                {"doc_name": "demo.pdf", "page_start": 1, "page_end": 1, "excerpt": "第一条规定", "chunk_text": "第一条规定"},
                {"doc_name": "demo.pdf", "page_start": 1, "page_end": 1, "excerpt": "第二条规定", "chunk_text": "第二条规定"},
                {"doc_name": "demo.pdf", "page_start": 2, "page_end": 2, "excerpt": "第三条规定", "chunk_text": "第三条规定"},
            ]
        }

    def fake_llm(*args, **kwargs):
        return {"text": "具体答案", "provider": "openai", "model": "gpt-4o-mini"}

    monkeypatch.setattr(chat_orchestrator, "hybrid_search", fake_search)
    monkeypatch.setattr(chat_orchestrator.LLMRouter, "route_and_generate", fake_llm)

    result = chat_with_citations("基本规定是什么", repo=None, entity_index=_DummyEntityIndex())
    assert len(result["citations"]) == 2
    assert result["citations"][0]["merged_count"] == 2
    assert "第一条规定" in result["citations"][0]["excerpt"]
    assert "第二条规定" in result["citations"][0]["excerpt"]


def test_chat_stub_answer_uses_specific_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_search(*args, **kwargs):
        return {
            "citations": [
                {
                    "doc_name": "demo.pdf",
                    "page_start": 1,
                    "page_end": 1,
                    "excerpt": "合同金额为5000万元，工期180天。",
                    "chunk_text": "合同金额为5000万元，工期180天。",
                }
            ]
        }

    def fake_llm(*args, **kwargs):
        return {"text": "根据证据，问题“xxx”的答案请参考引用内容。", "provider": "stub", "model": "stub-mvp"}

    monkeypatch.setattr(chat_orchestrator, "hybrid_search", fake_search)
    monkeypatch.setattr(chat_orchestrator.LLMRouter, "route_and_generate", fake_llm)

    result = chat_with_citations("基本规定", repo=None, entity_index=_DummyEntityIndex())
    assert "5000万元" in result["answer"]
    assert "180天" in result["answer"]
    assert "请参考引用内容" not in result["answer"]


def test_chat_constraint_mode_returns_structured_constraints(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_search(*args, **kwargs):
        return {
            "citations": [
                {
                    "doc_name": "spec.pdf",
                    "page_start": 18,
                    "page_end": 18,
                    "clause_id": "4.12.1(3)",
                    "is_mandatory": True,
                    "excerpt": "4.12.1(3) 试验时必须将插件拔出。",
                    "chunk_text": "4.12.1(3) 试验时必须将插件拔出。",
                }
            ]
        }

    monkeypatch.setattr(chat_orchestrator, "hybrid_search", fake_search)

    result = chat_with_citations("给出约束条款", repo=None, entity_index=_DummyEntityIndex(), mode="constraint")
    assert result["mode"] == "constraint"
    assert len(result["constraints"]) == 1
    assert result["constraints"][0]["clause_id"] == "4.12.1(3)"
    assert result["constraints"][0]["risk_level"] == "high"
    assert "evidence_full" in result["constraints"][0]
    assert "evidence_guard_lines" in result["constraints"][0]
    assert len(result["constraints_for_model"]) == 1
    assert "必须" in result["constraints_for_model"][0]["evidence"]
    assert "强制性条款" in result["answer"]


def test_chat_constraint_mode_keeps_full_text_for_model_context(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_search(*args, **kwargs):
        return {
            "citations": [
                {
                    "doc_name": "spec.pdf",
                    "page_start": 31,
                    "page_end": 31,
                    "clause_id": "4.9.6",
                    "excerpt": "4.9.6 抽真空时应采取防倒灌措施。",
                    "chunk_text": (
                        "4.9.6 在抽真空时，必须将不能承受真空机械强度的附件与油箱隔离。"
                        "对允许抽同样真空度的部件，应同时抽真空。"
                        "真空泵或真空机组应有防止突然停止或误操作引起油倒灌的措施。"
                    ),
                }
            ]
        }

    monkeypatch.setattr(chat_orchestrator, "hybrid_search", fake_search)

    result = chat_with_citations("给出约束条款", repo=None, entity_index=_DummyEntityIndex(), mode="constraint")
    item = result["constraints"][0]
    model_item = result["constraints_for_model"][0]
    assert "必须将不能承受真空机械强度的附件与油箱隔离" in item["evidence_full"]
    assert "必须" in item["evidence"]
    assert "必须将不能承受真空机械强度的附件与油箱隔离" in model_item["evidence"]


def test_chat_prompt_includes_question_and_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_search(*args, **kwargs):
        return {
            "citations": [
                {"doc_name": "demo.pdf", "page_start": 1, "page_end": 1, "excerpt": "项目经理张三", "chunk_text": "项目经理张三"}
            ]
        }

    def fake_llm(self, task_type: str, prompt: str, runtime_config=None):
        captured["task_type"] = task_type
        captured["prompt"] = prompt
        return {"text": "ok", "provider": "openai", "model": "gpt-4o-mini"}

    monkeypatch.setattr(chat_orchestrator, "hybrid_search", fake_search)
    monkeypatch.setattr(chat_orchestrator.LLMRouter, "route_and_generate", fake_llm)

    chat_with_citations("项目经理是谁", repo=None, entity_index=_DummyEntityIndex())
    assert captured["task_type"] == "qa_generate"
    assert "问题：项目经理是谁" in captured["prompt"]
    assert "证据：" in captured["prompt"]
    assert "[E1]" in captured["prompt"]
    assert "demo.pdf p.1: 项目经理张三" in captured["prompt"]
