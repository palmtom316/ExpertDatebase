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
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self) -> dict:
        return self._payload


def test_llm_router_uses_openai_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = InMemoryLLMLogRepo()

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example-openai.test/v1")

    calls: list[dict] = []

    def fake_post(url: str, headers: dict, json: dict, timeout: float):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _DummyResponse(
            {
                "choices": [{"message": {"content": "这是商业模型回答"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            }
        )

    monkeypatch.setattr("app.services.llm_router.requests.post", fake_post)

    router = LLMRouter(log_repo=repo)
    res = router.route_and_generate(task_type="qa_generate", prompt="合同金额是多少？")

    assert res["text"] == "这是商业模型回答"
    assert res["provider"] == "openai"
    assert res["model"] == "gpt-4o-mini"
    assert res["usage"]["tokens_in"] == 11
    assert res["usage"]["tokens_out"] == 7
    assert calls and calls[0]["url"] == "https://example-openai.test/v1/chat/completions"
    assert len(repo.logs) == 1
    assert repo.logs[0]["error"] is None


def test_llm_router_falls_back_to_stub_on_openai_error(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = InMemoryLLMLogRepo()

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")

    def fake_post(url: str, headers: dict, json: dict, timeout: float):
        raise RuntimeError("openai unavailable")

    monkeypatch.setattr("app.services.llm_router.requests.post", fake_post)

    router = LLMRouter(log_repo=repo)
    res = router.route_and_generate(task_type="qa_generate", prompt="测试回退")

    assert res["provider"] == "stub"
    assert "根据证据" in res["text"]
    assert len(repo.logs) == 1
    assert "openai unavailable" in str(repo.logs[0]["error"])
