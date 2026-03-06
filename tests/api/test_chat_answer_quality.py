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


def test_chat_constraint_mode_infers_mandatory_from_guard_terms(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_search(*args, **kwargs):
        return {
            "citations": [
                {
                    "doc_name": "spec.pdf",
                    "page_start": 13,
                    "page_end": 13,
                    "clause_id": "5.0.8",
                    "is_mandatory": False,
                    "excerpt": "5.0.8 经返修或加固处理仍不能满足安全或重要使用功能的分部工程及单位工程，严禁验收。",
                    "chunk_text": "5.0.8 经返修或加固处理仍不能满足安全或重要使用功能的分部工程及单位工程，严禁验收。",
                }
            ]
        }

    monkeypatch.setattr(chat_orchestrator, "hybrid_search", fake_search)

    result = chat_with_citations("给出约束条款", repo=None, entity_index=_DummyEntityIndex(), mode="constraint")
    assert result["constraints"][0]["is_mandatory"] is True
    assert result["constraints"][0]["risk_level"] == "high"
    assert "强制性条款 1 条" in result["answer"]


def test_chat_constraint_mode_infers_mandatory_from_only_allow_terms(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_search(*args, **kwargs):
        return {
            "citations": [
                {
                    "doc_name": "spec.pdf",
                    "page_start": 8,
                    "page_end": 8,
                    "clause_id": "4.2.2.2",
                    "is_mandatory": False,
                    "excerpt": "4.2.2.2 在 TN 系统中，应将 TN-C 系统改造为 TN-C-S、TN-S 系统或局部 TT 系统后，方可安装使用 RCD。在 TN-C-S 系统中，RCD 只允许使用在 N 线与 PE 线分开部分。",
                    "chunk_text": "4.2.2.2 在 TN 系统中，应将 TN-C 系统改造为 TN-C-S、TN-S 系统或局部 TT 系统后，方可安装使用 RCD。在 TN-C-S 系统中，RCD 只允许使用在 N 线与 PE 线分开部分。",
                }
            ]
        }

    monkeypatch.setattr(chat_orchestrator, "hybrid_search", fake_search)

    result = chat_with_citations("给出约束条款", repo=None, entity_index=_DummyEntityIndex(), mode="constraint")
    assert result["constraints"][0]["is_mandatory"] is True
    assert result["constraints"][0]["risk_level"] == "high"
    assert "强制性条款 1 条" in result["answer"]


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


def test_chat_qa_mode_filters_blank_and_noise_citations(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_search(*args, **kwargs):
        return {
            "citations": [
                {"doc_name": "", "doc_id": "", "page_start": 1, "page_end": 1, "excerpt": "", "chunk_text": ""},
                {
                    "doc_name": "",
                    "doc_id": "doc_spec",
                    "page_start": 1,
                    "page_end": 1,
                    "excerpt": "统一书号 494 定价：13.00元",
                    "chunk_text": "统一书号 494 定价：13.00元",
                },
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 12,
                    "page_end": 12,
                    "clause_id": "4.8.4",
                    "excerpt": "4.8.4 冷却装置安装应符合下列规定。",
                    "chunk_text": "4.8.4 冷却装置安装应符合下列规定。",
                },
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 13,
                    "page_end": 13,
                    "clause_id": "4.8.5",
                    "excerpt": "4.8.5 冷却装置不得渗漏。",
                    "chunk_text": "4.8.5 冷却装置不得渗漏。",
                },
            ]
        }

    def fake_llm(*args, **kwargs):
        return {"text": "具体答案", "provider": "openai", "model": "gpt-4o-mini"}

    monkeypatch.setattr(chat_orchestrator, "hybrid_search", fake_search)
    monkeypatch.setattr(chat_orchestrator.LLMRouter, "route_and_generate", fake_llm)

    result = chat_with_citations("冷却装置安装要求是什么", repo=None, entity_index=_DummyEntityIndex())

    assert len(result["citations"]) == 2
    assert all(c["doc_name"] == "spec.pdf" for c in result["citations"])
    assert all((c.get("excerpt") or c.get("chunk_text")) for c in result["citations"])


def test_dedupe_citations_prefers_populated_variant_over_blank_variant() -> None:
    out = chat_orchestrator._dedupe_citations(  # type: ignore[attr-defined]
        [
            {
                "doc_name": "",
                "doc_id": "doc_spec",
                "page_start": 18,
                "page_end": 18,
                "clause_id": "",
                "excerpt": "",
                "chunk_text": "",
            },
            {
                "doc_name": "spec.pdf",
                "doc_id": "doc_spec",
                "page_start": 18,
                "page_end": 18,
                "clause_id": "4.12.1(3)",
                "excerpt": "4.12.1(3) 试验时必须将插件拔出。",
                "chunk_text": "4.12.1(3) 试验时必须将插件拔出。",
            },
        ]
    )

    assert len(out) == 1
    assert out[0]["doc_name"] == "spec.pdf"
    assert out[0]["clause_id"] == "4.12.1(3)"
    assert "必须" in (out[0].get("excerpt") or "")


def test_chat_constraint_mode_filters_blank_noise_and_dedupes_redundant_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_search(*args, **kwargs):
        return {
            "citations": [
                {"doc_name": "", "doc_id": "", "page_start": 1, "page_end": 1, "excerpt": "", "chunk_text": ""},
                {
                    "doc_name": "",
                    "doc_id": "doc_spec",
                    "page_start": 1,
                    "page_end": 1,
                    "excerpt": "统一书号 494 定价：13.00元",
                    "chunk_text": "统一书号 494 定价：13.00元",
                },
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 31,
                    "page_end": 31,
                    "clause_id": "4.9.6",
                    "source_type": "text",
                    "excerpt": "4.9.6 抽真空时必须将不能承受真空机械强度的附件与油箱隔离。",
                    "chunk_text": "4.9.6 抽真空时必须将不能承受真空机械强度的附件与油箱隔离。",
                },
                {
                    "doc_name": "",
                    "doc_id": "doc_spec",
                    "page_start": 31,
                    "page_end": 31,
                    "clause_id": "4.9.6",
                    "source_type": "text",
                    "excerpt": "",
                    "chunk_text": "",
                },
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 31,
                    "page_end": 31,
                    "clause_id": "4.9.6",
                    "source_type": "explanation",
                    "excerpt": "条文说明：为防止油倒灌，应配置防倒灌措施。",
                    "chunk_text": "条文说明：为防止油倒灌，应配置防倒灌措施。",
                },
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 32,
                    "page_end": 32,
                    "clause_id": "4.9.7",
                    "source_type": "text",
                    "excerpt": "4.9.7 真空泵或真空机组应有防止误操作引起油倒灌的措施。",
                    "chunk_text": "4.9.7 真空泵或真空机组应有防止误操作引起油倒灌的措施。",
                },
            ]
        }

    monkeypatch.setattr(chat_orchestrator, "hybrid_search", fake_search)

    result = chat_with_citations("给出抽真空相关约束", repo=None, entity_index=_DummyEntityIndex(), mode="constraint")

    assert all(item["doc_name"] for item in result["constraints"])
    assert all(item["evidence"] for item in result["constraints"])
    assert sum(1 for x in result["constraints"] if x["clause_id"] == "4.9.6") == 1
    assert {"4.9.6", "4.9.7"} <= {x["clause_id"] for x in result["constraints"]}


def test_chat_constraint_mode_caps_output_for_bid_writing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAT_CONSTRAINT_MAX_ITEMS", "12")

    def fake_search(*args, **kwargs):
        return {
            "citations": [
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": idx,
                    "page_end": idx,
                    "clause_id": f"5.1.{idx}",
                    "source_type": "text",
                    "excerpt": f"5.1.{idx} 施工时应执行第 {idx} 项要求。",
                    "chunk_text": f"5.1.{idx} 施工时应执行第 {idx} 项要求。",
                }
                for idx in range(1, 31)
            ]
        }

    monkeypatch.setattr(chat_orchestrator, "hybrid_search", fake_search)

    result = chat_with_citations("给出投标约束条款", repo=None, entity_index=_DummyEntityIndex(), mode="constraint")

    assert len(result["constraints"]) == 12
    assert len(result["constraints_for_model"]) == 12
    assert len(result["citations"]) == 12
    assert all(item["doc_name"] == "spec.pdf" for item in result["constraints"])


def test_chat_constraint_mode_prefers_specific_phrase_match_over_generic_intro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_search(*args, **kwargs):
        return {
            "citations": [
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 14,
                    "page_end": 14,
                    "clause_id": "3.0.1",
                    "source_type": "text",
                    "excerpt": "3.0.1 电气设备交接试验应符合本标准规定。",
                    "chunk_text": "3.0.1 电气设备交接试验应符合本标准规定。",
                },
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 17,
                    "page_end": 17,
                    "clause_id": "4.0.1",
                    "source_type": "text",
                    "excerpt": "4.0.1 变压器试验前应做好准备工作。",
                    "chunk_text": "4.0.1 变压器试验前应做好准备工作。",
                },
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 67,
                    "page_end": 68,
                    "clause_id": "18.0.5",
                    "source_type": "text",
                    "excerpt": "18.0.5 变压器交接试验中的交流耐压试验应符合下列规定。",
                    "chunk_text": "18.0.5 变压器交接试验中的交流耐压试验应符合下列规定。",
                },
            ]
        }

    monkeypatch.setattr(chat_orchestrator, "hybrid_search", fake_search)

    result = chat_with_citations(
        "变压器交接试验中的交流耐压试验有哪些规定？",
        repo=None,
        entity_index=_DummyEntityIndex(),
        mode="constraint",
    )

    assert result["citations"][0]["clause_id"] == "18.0.5"


def test_chat_constraint_mode_prefers_topic_specific_clause_over_generic_main_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_search(*args, **kwargs):
        return {
            "citations": [
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 31,
                    "page_end": 31,
                    "clause_id": "3.3.13",
                    "source_type": "text",
                    "excerpt": (
                        "3.3.12 塑料护套线直敷布线应符合下列规定："
                        "布线前应确认穿梁、墙、楼板等建筑结构上的套管已安装到位。"
                        "3.3.13 钢索配线的钢索吊装及线路敷设应符合设计要求。"
                    ),
                    "chunk_text": (
                        "3.3.12 塑料护套线直敷布线应符合下列规定："
                        "布线前应确认穿梁、墙、楼板等建筑结构上的套管已安装到位。"
                        "3.3.13 钢索配线的钢索吊装及线路敷设应符合设计要求。"
                    ),
                },
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 46,
                    "page_end": 46,
                    "clause_id": "6.1",
                    "source_type": "text",
                    "excerpt": "6 电动机、电加热器及电动执行机构 6.1 主控项目 6.1.1 外露可导电部分必须与保护导体可靠连接。",
                    "chunk_text": "6 电动机、电加热器及电动执行机构 6.1 主控项目 6.1.1 外露可导电部分必须与保护导体可靠连接。",
                },
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 78,
                    "page_end": 78,
                    "clause_id": "15.1",
                    "source_type": "text",
                    "excerpt": "15.1 槽板配线主控项目应符合下列规定。",
                    "chunk_text": "15.1 槽板配线主控项目应符合下列规定。",
                },
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 80,
                    "page_end": 83,
                    "clause_id": "16.1",
                    "source_type": "text",
                    "excerpt": "16.1 钢索配线主控项目应符合下列规定。",
                    "chunk_text": "16.1 钢索配线主控项目应符合下列规定。",
                },
            ]
        }

    monkeypatch.setattr(chat_orchestrator, "hybrid_search", fake_search)

    result = chat_with_citations("钢索配线的主控项目有哪些要求？", repo=None, entity_index=_DummyEntityIndex(), mode="constraint")

    assert result["citations"][0]["clause_id"] == "16.1"


def test_constraint_score_rewards_multi_term_coverage_margin() -> None:
    question = "钢索配线的主控项目有哪些要求？"
    generic = {
        "doc_name": "spec.pdf",
        "doc_id": "doc_spec",
        "page_start": 31,
        "page_end": 31,
        "clause_id": "3.3.13",
        "source_type": "text",
        "excerpt": (
            "3.3.12 塑料护套线直敷布线应符合下列规定："
            "布线前应确认穿梁、墙、楼板等建筑结构上的套管已安装到位。"
            "3.3.13 钢索配线的钢索吊装及线路敷设应符合设计要求。"
        ),
        "chunk_text": (
            "3.3.12 塑料护套线直敷布线应符合下列规定："
            "布线前应确认穿梁、墙、楼板等建筑结构上的套管已安装到位。"
            "3.3.13 钢索配线的钢索吊装及线路敷设应符合设计要求。"
        ),
    }
    specific = {
        "doc_name": "spec.pdf",
        "doc_id": "doc_spec",
        "page_start": 80,
        "page_end": 83,
        "clause_id": "16.1",
        "source_type": "text",
        "excerpt": "16 钢索配线 16.1 主控项目 16.1.1 钢索配线应采用镀锌钢索，不应采用含油芯的钢索。",
        "chunk_text": "16 钢索配线 16.1 主控项目 16.1.1 钢索配线应采用镀锌钢索，不应采用含油芯的钢索。",
    }

    generic_score = chat_orchestrator._constraint_citation_score(question, generic)  # type: ignore[attr-defined]
    specific_score = chat_orchestrator._constraint_citation_score(question, specific)  # type: ignore[attr-defined]

    assert specific_score > generic_score + 3.0


def test_chat_constraint_mode_uses_higher_top_k_for_doc_scoped_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, int] = {}

    def fake_search(*args, **kwargs):
        captured["top_k"] = kwargs["top_k"]
        return {"citations": []}

    monkeypatch.setenv("CHAT_SEARCH_TOP_K", "16")
    monkeypatch.setenv("CHAT_SEARCH_TOP_K_DOC_SCOPE", "32")
    monkeypatch.setenv("CHAT_SEARCH_TOP_K_CONSTRAINT_DOC_SCOPE", "48")
    monkeypatch.setattr(chat_orchestrator, "hybrid_search", fake_search)

    chat_with_citations(
        "给出投标约束条款",
        repo=None,
        entity_index=_DummyEntityIndex(),
        mode="constraint",
        search_filter={"must": [{"key": "version_id", "match": {"value": "ver_demo"}}]},
    )

    assert captured["top_k"] == 48


def test_extract_question_match_terms_keeps_parallel_capacitor_topic() -> None:
    terms = chat_orchestrator._extract_question_match_terms(  # type: ignore[attr-defined]
        "并联电容器的交流耐压试验应符合哪些规定？"
    )

    assert "并联电容器" in terms


def test_constraint_score_rewards_parallel_capacitor_exact_topic() -> None:
    question = "并联电容器的交流耐压试验应符合哪些规定？"
    generic = {
        "doc_name": "spec.pdf",
        "doc_id": "doc_spec",
        "page_start": 14,
        "page_end": 14,
        "clause_id": "3.0.1",
        "source_type": "text",
        "excerpt": "3.0.1 电气设备应按本标准进行交流耐压试验，且应符合下列规定。",
        "chunk_text": "3.0.1 电气设备应按本标准进行交流耐压试验，且应符合下列规定。",
    }
    specific = {
        "doc_name": "spec.pdf",
        "doc_id": "doc_spec",
        "page_start": 67,
        "page_end": 67,
        "clause_id": "18.0.5",
        "source_type": "text",
        "excerpt": "18.0.5 并联电容器的交流耐压试验，应符合下列规定。",
        "chunk_text": "18.0.5 并联电容器的交流耐压试验，应符合下列规定。",
    }

    generic_score = chat_orchestrator._constraint_citation_score(question, generic)  # type: ignore[attr-defined]
    specific_score = chat_orchestrator._constraint_citation_score(question, specific)  # type: ignore[attr-defined]

    assert specific_score > generic_score + 4.0


def test_constraint_score_rewards_ascii_term_matches_for_rcd_topology() -> None:
    question = "在TN系统中应将TN-C系统改造为何种系统后方可安装使用RCD？"
    generic = {
        "doc_name": "spec.pdf",
        "page_start": 9,
        "page_end": 9,
        "clause_id": "4.5",
        "source_type": "text",
        "excerpt": "4.5 可不装RCD的情况。具备下列条件的电气设备和场所，可不装RCD。",
        "chunk_text": "4.5 可不装RCD的情况。具备下列条件的电气设备和场所，可不装RCD。",
    }
    specific = {
        "doc_name": "spec.pdf",
        "page_start": 8,
        "page_end": 8,
        "clause_id": "4.2.2.2",
        "source_type": "text",
        "excerpt": "4.2.2.2 在 TN 系统中，应将 TN-C 系统改造为 TN-C-S、TN-S 系统或局部 TT 系统后，方可安装使用 RCD。",
        "chunk_text": "4.2.2.2 在 TN 系统中，应将 TN-C 系统改造为 TN-C-S、TN-S 系统或局部 TT 系统后，方可安装使用 RCD。",
    }

    generic_score = chat_orchestrator._constraint_citation_score(question, generic)  # type: ignore[attr-defined]
    specific_score = chat_orchestrator._constraint_citation_score(question, specific)  # type: ignore[attr-defined]

    assert specific_score > generic_score + 3.0


def test_chat_constraint_mode_drops_same_page_weaker_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_search(*args, **kwargs):
        return {
            "citations": [
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 67,
                    "page_end": 68,
                    "clause_id": "18.0.5",
                    "source_type": "text",
                    "excerpt": "18.0.5 并联电容器的交流耐压试验，应符合下列规定。",
                    "chunk_text": "18.0.5 并联电容器的交流耐压试验，应符合下列规定。",
                },
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 67,
                    "page_end": 67,
                    "clause_id": "",
                    "source_type": "",
                    "excerpt": "并联电容器的交流耐压试验，应符合下列规定。",
                    "chunk_text": "并联电容器的交流耐压试验，应符合下列规定。",
                },
            ]
        }

    monkeypatch.setattr(chat_orchestrator, "hybrid_search", fake_search)

    result = chat_with_citations(
        "并联电容器的交流耐压试验应符合哪些规定？",
        repo=None,
        entity_index=_DummyEntityIndex(),
        mode="constraint",
    )

    assert len(result["citations"]) == 1
    assert result["citations"][0]["clause_id"] == "18.0.5"


def test_chat_constraint_mode_filters_watermark_and_parse_artifacts(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_search(*args, **kwargs):
        return {
            "citations": [
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 4,
                    "page_end": 4,
                    "excerpt": "标准分享网 www.bzfxw.com 免费下载",
                    "chunk_text": "标准分享网 www.bzfxw.com 免费下载",
                },
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 38,
                    "page_end": 38,
                    "excerpt": "value of the article.# 附录A 新装电力变压器及油浸电抗器不需干燥的条件",
                    "chunk_text": "value of the article.# 附录A 新装电力变压器及油浸电抗器不需干燥的条件",
                },
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 8,
                    "page_end": 8,
                    "excerpt": "value of the product.# GB/T 13955—2017 4.2.2.2 在 TN 系统中方可安装使用 RCD。",
                    "chunk_text": "value of the product.# GB/T 13955—2017 4.2.2.2 在 TN 系统中方可安装使用 RCD。",
                },
                {
                    "doc_name": "spec.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 36,
                    "page_end": 36,
                    "clause_id": "5.3.1",
                    "source_type": "text",
                    "excerpt": "5.3.1 电力变压器本体检查应符合产品技术文件要求。",
                    "chunk_text": "5.3.1 电力变压器本体检查应符合产品技术文件要求。",
                },
            ]
        }

    monkeypatch.setattr(chat_orchestrator, "hybrid_search", fake_search)

    result = chat_with_citations(
        "电力变压器安装前，本体检查应符合哪些规定？",
        repo=None,
        entity_index=_DummyEntityIndex(),
        mode="constraint",
    )

    assert len(result["citations"]) == 1
    assert result["citations"][0]["clause_id"] == "5.3.1"


def test_chat_constraint_mode_prefers_tn_rcd_topology_clause(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_search(*args, **kwargs):
        return {
            "citations": [
                {
                    "doc_name": "GB-T13955-2017.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 9,
                    "page_end": 9,
                    "clause_id": "4.5",
                    "source_type": "text",
                    "route": "dense",
                    "excerpt": "4.5 可不装RCD的情况。具备下列条件的电气设备和场所，可不装RCD。",
                    "chunk_text": "4.5 可不装RCD的情况。具备下列条件的电气设备和场所，可不装RCD。",
                },
                {
                    "doc_name": "GB-T13955-2017.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 9,
                    "page_end": 9,
                    "clause_id": "4.4.1",
                    "source_type": "text",
                    "route": "dense",
                    "excerpt": "4.4.1 末端保护。下列设备和场所应安装末端保护RCD。",
                    "chunk_text": "4.4.1 末端保护。下列设备和场所应安装末端保护RCD。",
                },
                {
                    "doc_name": "GB-T13955-2017.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 8,
                    "page_end": 8,
                    "clause_id": "4.2.4",
                    "source_type": "text",
                    "route": "dense",
                    "excerpt": "4.2.4 对 IT 系统的防护要求。IT 系统的电气线路或电气设备可以保护性安装 RCD。",
                    "chunk_text": "4.2.4 对 IT 系统的防护要求。IT 系统的电气线路或电气设备可以保护性安装 RCD。",
                },
                {
                    "doc_name": "GB-T13955-2017.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 8,
                    "page_end": 8,
                    "clause_id": "4.2.1",
                    "source_type": "text",
                    "route": "dense",
                    "excerpt": "4.2.1 一般要求。当电路发生绝缘损坏造成接地故障，其接地故障电流值小于过电流保护装置的动作电流值时，应安装 RCD。",
                    "chunk_text": "4.2.1 一般要求。当电路发生绝缘损坏造成接地故障，其接地故障电流值小于过电流保护装置的动作电流值时，应安装 RCD。",
                },
                {
                    "doc_name": "GB-T13955-2017.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 8,
                    "page_end": 8,
                    "clause_id": "4.2.2.1",
                    "source_type": "text",
                    "route": "dense",
                    "excerpt": "4.2.2.1 采用 RCD 的 TN-C 系统，应根据电击防护措施的具体情况，将电气设备外露可接近导体独立接地，形成局部 TT 系统。",
                    "chunk_text": "4.2.2.1 采用 RCD 的 TN-C 系统，应根据电击防护措施的具体情况，将电气设备外露可接近导体独立接地，形成局部 TT 系统。",
                },
                {
                    "doc_name": "GB-T13955-2017.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 8,
                    "page_end": 8,
                    "clause_id": "4.2.2.2",
                    "source_type": "text",
                    "route": "dense",
                    "excerpt": "4.2.2.2 在 TN 系统中，应将 TN-C 系统改造为 TN-C-S、TN-S 系统或局部 TT 系统后，方可安装使用 RCD。在 TN-C-S 系统中，RCD 只允许使用在 N 线与 PE 线分开部分。",
                    "chunk_text": "4.2.2.2 在 TN 系统中，应将 TN-C 系统改造为 TN-C-S、TN-S 系统或局部 TT 系统后，方可安装使用 RCD。在 TN-C-S 系统中，RCD 只允许使用在 N 线与 PE 线分开部分。",
                },
                {
                    "doc_name": "GB-T13955-2017.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 8,
                    "page_end": 8,
                    "clause_id": "4.2.3",
                    "source_type": "text",
                    "route": "dense",
                    "excerpt": "4.2.3 对 TT 系统的防护要求。TT 系统的电气线路或电气设备应装设 RCD。",
                    "chunk_text": "4.2.3 对 TT 系统的防护要求。TT 系统的电气线路或电气设备应装设 RCD。",
                },
                {
                    "doc_name": "GB-T13955-2017.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 8,
                    "page_end": 8,
                    "clause_id": "4.1",
                    "source_type": "text",
                    "route": "dense",
                    "excerpt": "4.1 RCD 用于间接接触电击事故防护时，应正确地与电网系统接地型式相配合。",
                    "chunk_text": "4.1 RCD 用于间接接触电击事故防护时，应正确地与电网系统接地型式相配合。",
                },
            ]
        }

    monkeypatch.setattr(chat_orchestrator, "hybrid_search", fake_search)

    result = chat_with_citations(
        "在TN系统中安装使用RCD前应如何处理？",
        repo=None,
        entity_index=_DummyEntityIndex(),
        mode="constraint",
    )

    assert result["constraints"][0]["clause_id"] == "4.2.2.2"
    assert result["constraints"][0]["is_mandatory"] is True
    assert result["constraints"][0]["risk_level"] == "high"


def test_chat_constraint_mode_keeps_clause_text_when_same_page_sparse_artifact_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_search(*args, **kwargs):
        return {
            "citations": [
                {
                    "doc_name": "GB-T13955-2017.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 8,
                    "page_end": 8,
                    "clause_id": "4.2.2.2",
                    "source_type": "text",
                    "route": "dense",
                    "excerpt": "4.2.2.2 在 TN 系统中，应将 TN-C 系统改造为 TN-C-S、TN-S 系统或局部 TT 系统后，方可安装使用 RCD。",
                    "chunk_text": "4.2.2.2 在 TN 系统中，应将 TN-C 系统改造为 TN-C-S、TN-S 系统或局部 TT 系统后，方可安装使用 RCD。在 TN-C-S 系统中，RCD 只允许使用在 N 线与 PE 线分开部分。",
                },
                {
                    "doc_name": "",
                    "doc_id": "doc_spec",
                    "page_start": 8,
                    "page_end": 8,
                    "clause_id": "",
                    "source_type": "",
                    "route": "sparse",
                    "excerpt": "value of the product.# GB/T 13955—2017 术语页噪声",
                    "chunk_text": "value of the product.# GB/T 13955—2017 术语页噪声",
                },
                {
                    "doc_name": "GB-T13955-2017.pdf",
                    "doc_id": "doc_spec",
                    "page_start": 9,
                    "page_end": 9,
                    "clause_id": "4.5",
                    "source_type": "text",
                    "route": "dense",
                    "excerpt": "4.5 可不装RCD的情况。具备下列条件的电气设备和场所，可不装RCD。",
                    "chunk_text": "4.5 可不装RCD的情况。具备下列条件的电气设备和场所，可不装RCD。",
                },
            ]
        }

    monkeypatch.setattr(chat_orchestrator, "hybrid_search", fake_search)

    result = chat_with_citations(
        "在TN系统中安装使用RCD前应如何处理？",
        repo=None,
        entity_index=_DummyEntityIndex(),
        mode="constraint",
    )

    assert result["constraints"][0]["clause_id"] == "4.2.2.2"
    assert "value of the product" not in result["constraints"][0]["evidence_full"].lower()
