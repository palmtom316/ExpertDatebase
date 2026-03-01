import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.main import app
from app.services.chat_orchestrator import _build_expandable_evidence
from app.services.llm_log_repo import InMemoryLLMLogRepo
from app.services.llm_router import LLMRouter


def test_admin_eval_routes_cover_run_and_trend() -> None:
    paths = {r.path for r in app.routes}
    assert "/api/admin/eval/runs/start" in paths
    assert "/api/admin/eval/trends" in paths
    assert "/api/admin/eval/datasets/add" in paths


def test_docs_list_route_registered() -> None:
    paths = {r.path for r in app.routes}
    assert "/api/docs" in paths


def test_expandable_evidence_contains_before_after_context() -> None:
    citations = [
        {
            "doc_name": "a.pdf",
            "page_start": 1,
            "page_end": 1,
            "excerpt": "合同金额5000万元",
            "chunk_text": "本项目合同金额5000万元，签订日期为2023-01-01，业主单位为某电力公司。",
        }
    ]
    out = _build_expandable_evidence(citations)
    assert out[0]["context_before"]
    assert out[0]["excerpt"]
    assert out[0]["context_after"]


def test_llm_router_masks_sensitive_text_before_external_call(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = InMemoryLLMLogRepo()

    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example-openai.test/v1")

    captured = {}

    class _DummyResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            }

    def fake_post(url: str, headers: dict, json: dict, timeout: float):
        captured["body"] = json
        return _DummyResponse()

    monkeypatch.setattr("app.services.llm_router.requests.post", fake_post)

    router = LLMRouter(log_repo=repo)
    router.route_and_generate(
        task_type="qa_generate",
        prompt="联系人13812345678，邮箱abc@test.com",
        runtime_config={
            "llm_provider": "openai",
            "llm_api_key": "sk-test",
        },
    )

    user_prompt = captured["body"]["messages"][1]["content"]
    assert "13812345678" not in user_prompt
    assert "abc@test.com" not in user_prompt


def test_llm_router_circuit_breaker_opens_after_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = InMemoryLLMLogRepo()

    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("LLM_CB_FAIL_THRESHOLD", "2")
    monkeypatch.setenv("LLM_CB_COOLDOWN_SECONDS", "60")

    def fake_post(url: str, headers: dict, json: dict, timeout: float):
        raise RuntimeError("upstream down")

    monkeypatch.setattr("app.services.llm_router.requests.post", fake_post)

    router = LLMRouter(log_repo=repo)
    runtime = {
        "llm_provider": "openai",
        "llm_api_key": "sk-test",
    }
    router.route_and_generate(task_type="qa_generate", prompt="q1", runtime_config=runtime)
    router.route_and_generate(task_type="qa_generate", prompt="q2", runtime_config=runtime)
    res = router.route_and_generate(task_type="qa_generate", prompt="q3", runtime_config=runtime)

    assert res["provider"] == "stub"
    assert any("circuit_open" in str(x.get("metadata_json", {})) for x in repo.logs)
