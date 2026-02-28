import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.services.llm_log_repo import InMemoryLLMLogRepo
from app.services.llm_router import LLMRouter


class _DummyResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "choices": [{"message": {"content": "ok-from-override"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        }


def test_llm_router_accepts_runtime_config_override(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = InMemoryLLMLogRepo()
    calls = []

    def fake_post(url: str, headers: dict, json: dict, timeout: float):
        calls.append({"url": url, "headers": headers, "json": json})
        return _DummyResponse()

    monkeypatch.setattr("app.services.llm_router.requests.post", fake_post)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "stub")

    router = LLMRouter(log_repo=repo)
    res = router.route_and_generate(
        task_type="qa_generate",
        prompt="请回答",
        runtime_config={
            "llm_provider": "openai",
            "llm_api_key": "runtime-key",
            "llm_model": "gpt-4o-mini",
            "llm_base_url": "https://runtime-openai.test/v1",
        },
    )

    assert res["provider"] == "openai"
    assert calls and calls[0]["url"] == "https://runtime-openai.test/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer runtime-key"


def test_eval_quality_route_registered() -> None:
    from app.main import app

    paths = {r.path for r in app.routes}
    assert "/api/admin/eval/llm-quality" in paths
