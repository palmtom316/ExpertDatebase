import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.services.search_service import RuntimeRerankClient


class _Resp:
    status_code = 200

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _hits() -> list[dict]:
    return [
        {"id": "h1", "score": 0.11, "payload": {"chunk_text": "第一条 基本规定"}},
        {"id": "h2", "score": 0.12, "payload": {"chunk_text": "第二条 技术要求"}},
        {"id": "h3", "score": 0.13, "payload": {"chunk_text": "第三条 验收"}},
    ]


def test_native_rerank_uses_rerank_endpoint_and_reorders(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_post(url: str, headers: dict, json: dict, timeout: float):
        calls.append({"url": url, "headers": headers, "json": json})
        return _Resp({"results": [{"index": 2, "relevance_score": 0.92}, {"index": 0, "relevance_score": 0.55}]})

    monkeypatch.setattr("app.services.search_service.requests.post", fake_post)

    out = RuntimeRerankClient().rerank_hits(
        question="验收",
        hits=_hits(),
        runtime_config={
            "rerank_provider": "openai",
            "rerank_api_key": "rk",
            "rerank_model": "BAAI/bge-reranker-v2-m3",
            "rerank_base_url": "https://runtime-openai.test/v1",
        },
    )

    assert calls and calls[0]["url"] == "https://runtime-openai.test/v1/rerank"
    assert calls[0]["json"]["query"] == "验收"
    assert calls[0]["json"]["documents"][0] == "第一条 基本规定"
    assert [x["id"] for x in out] == ["h3", "h1", "h2"]


def test_native_rerank_falls_back_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _ErrResp:
        def raise_for_status(self) -> None:
            raise RuntimeError("boom")

        def json(self) -> dict:
            return {}

    def fake_post(url: str, headers: dict, json: dict, timeout: float):
        return _ErrResp()

    monkeypatch.setattr("app.services.search_service.requests.post", fake_post)

    out = RuntimeRerankClient().rerank_hits(
        question="基本规定",
        hits=_hits(),
        runtime_config={
            "rerank_provider": "openai",
            "rerank_api_key": "rk",
            "rerank_model": "BAAI/bge-reranker-v2-m3",
            "rerank_base_url": "https://runtime-openai.test/v1",
        },
    )

    assert len(out) == 3
