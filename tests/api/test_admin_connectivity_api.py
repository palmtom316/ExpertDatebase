import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.main import app


class _DummyResponse:
    def __init__(self, status_code: int = 200, err: Exception | None = None, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._err = err
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        if self._err:
            raise self._err

    def json(self) -> dict:
        return self._payload


def test_admin_connectivity_route_registered() -> None:
    paths = {r.path for r in app.routes}
    assert "/api/admin/connectivity/test" in paths


def test_mineru_connectivity_success(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict = {}

    def fake_post(url: str, headers: dict, files: dict, timeout: float, **kwargs):
        called["url"] = url
        called["headers"] = headers
        called["files"] = files
        called["timeout"] = timeout
        return _DummyResponse(status_code=200)

    monkeypatch.setattr("app.api.admin_connectivity.requests.post", fake_post)

    client = TestClient(app)
    resp = client.post(
        "/api/admin/connectivity/test",
        json={
            "target": "mineru",
            "mineru_api_base": "https://mineru.example.com",
            "mineru_api_key": "mineru-key",
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["target"] == "mineru"
    assert called["url"] == "https://mineru.example.com/parse"
    assert payload["detail"]["mode"] == "parse_upload"


def test_mineru_connectivity_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url: str, headers: dict, files: dict, timeout: float, **kwargs):
        return _DummyResponse(status_code=401, err=RuntimeError("unauthorized"))

    monkeypatch.setattr("app.api.admin_connectivity.requests.post", fake_post)

    client = TestClient(app)
    resp = client.post(
        "/api/admin/connectivity/test",
        json={
            "target": "mineru",
            "mineru_api_base": "https://mineru.example.com",
            "mineru_api_key": "wrong",
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is False
    assert payload["target"] == "mineru"
    assert "unauthorized" in payload["message"]


def test_mineru_connectivity_cloud_v4_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict = {}

    def fake_post(url: str, headers: dict, timeout: float, **kwargs):
        called["url"] = url
        called["headers"] = headers
        called["json"] = kwargs.get("json")
        return _DummyResponse(status_code=200, payload={"code": 0, "data": {"batch_id": "batch_123", "file_urls": [{"url": "https://upload.example.com/file.pdf"}]}})

    monkeypatch.setattr("app.api.admin_connectivity.requests.post", fake_post)

    client = TestClient(app)
    resp = client.post(
        "/api/admin/connectivity/test",
        json={
            "target": "mineru",
            "mineru_api_base": "https://mineru.net/api/v4/extract/task",
            "mineru_api_key": "mineru-key",
            "mineru_token": "token-1",
            "mineru_model_version": "index_pro",
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["detail"]["mode"] == "cloud_v4"
    # The connectivity test now uses file-urls/batch (auth check without quota use)
    assert called["url"] == "https://mineru.net/api/v4/file-urls/batch"
    assert called["headers"]["Authorization"] == "Bearer mineru-key"
    assert called["headers"]["token"] == "token-1"
    assert called["json"]["files"][0]["name"] == "connectivity_test.pdf"
    assert called["json"]["files"][0]["is_ocr"] is False


def test_mineru_connectivity_cloud_v4_fails_when_upload_url_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url: str, headers: dict, timeout: float, **kwargs):
        return _DummyResponse(status_code=200, payload={"success": True, "data": {"batchId": "batch_123", "files": []}})

    monkeypatch.setattr("app.api.admin_connectivity.requests.post", fake_post)

    client = TestClient(app)
    resp = client.post(
        "/api/admin/connectivity/test",
        json={
            "target": "mineru",
            "mineru_api_base": "https://mineru.net/api/v4/extract/task",
            "mineru_api_key": "mineru-key",
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is False
    assert "上传地址为空" in payload["message"]


def test_mineru_connectivity_strips_bearer_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict = {}

    def fake_post(url: str, headers: dict, files: dict, timeout: float, **kwargs):
        called["headers"] = headers
        return _DummyResponse(status_code=200)

    monkeypatch.setattr("app.api.admin_connectivity.requests.post", fake_post)

    client = TestClient(app)
    resp = client.post(
        "/api/admin/connectivity/test",
        json={
            "target": "mineru",
            "mineru_api_base": "https://mineru.example.com",
            "mineru_api_key": "Bearer mineru-key",
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert called["headers"]["Authorization"] == "Bearer mineru-key"


def test_embedding_connectivity_success(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict = {}

    def fake_post(url: str, headers: dict, json: dict, timeout: float, **kwargs):
        called["url"] = url
        called["headers"] = headers
        called["json"] = json
        return _DummyResponse(status_code=200, payload={"data": [{"embedding": [0.1, 0.2, 0.3]}]})

    monkeypatch.setattr("app.api.admin_connectivity.requests.post", fake_post)

    client = TestClient(app)
    resp = client.post(
        "/api/admin/connectivity/test",
        json={
            "target": "embedding",
            "embedding_provider": "openai",
            "embedding_api_key": "emb-key",
            "embedding_model": "text-embedding-3-small",
            "embedding_base_url": "https://runtime-openai.test/v1",
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["target"] == "embedding"
    assert called["url"] == "https://runtime-openai.test/v1/embeddings"
    assert called["headers"]["Authorization"] == "Bearer emb-key"
    assert called["json"]["model"] == "text-embedding-3-small"


def test_rerank_connectivity_success(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict = {}

    def fake_post(url: str, headers: dict, json: dict, timeout: float, **kwargs):
        called["url"] = url
        called["headers"] = headers
        called["json"] = json
        return _DummyResponse(status_code=200, payload={"results": [{"index": 0, "relevance_score": 0.9}]})

    monkeypatch.setattr("app.api.admin_connectivity.requests.post", fake_post)

    client = TestClient(app)
    resp = client.post(
        "/api/admin/connectivity/test",
        json={
            "target": "rerank",
            "rerank_provider": "openai",
            "rerank_api_key": "rr-key",
            "rerank_model": "BAAI/bge-reranker-v2-m3",
            "rerank_base_url": "https://runtime-openai.test/v1",
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["target"] == "rerank"
    assert called["url"] == "https://runtime-openai.test/v1/rerank"
    assert called["headers"]["Authorization"] == "Bearer rr-key"
    assert called["json"]["query"] == "connectivity test"


def test_unknown_target_returns_validation_message() -> None:
    client = TestClient(app)
    resp = client.post("/api/admin/connectivity/test", json={"target": "unknown"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is False
    assert "target 必须是 mineru、llm、embedding 或 rerank" in payload["message"]


def test_llm_connectivity_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_route_and_generate(self, task_type: str, prompt: str, runtime_config: dict | None = None):
        return {
            "text": "OK",
            "provider": "openai",
            "model": "gpt-4o-mini",
            "latency_ms": 18,
            "usage": {"tokens_in": 2, "tokens_out": 1},
        }

    monkeypatch.setattr("app.api.admin_connectivity.LLMRouter.route_and_generate", fake_route_and_generate)

    client = TestClient(app)
    resp = client.post(
        "/api/admin/connectivity/test",
        json={
            "target": "llm",
            "llm_provider": "openai",
            "llm_api_key": "sk-test",
            "llm_model": "gpt-4o-mini",
            "llm_base_url": "https://api.openai.com/v1",
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["target"] == "llm"
    assert payload["detail"]["provider"] == "openai"


def test_llm_connectivity_detects_fallback_as_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_route_and_generate(self, task_type: str, prompt: str, runtime_config: dict | None = None):
        return {
            "text": "stub",
            "provider": "stub",
            "model": "stub-mvp",
            "latency_ms": 5,
            "usage": {"tokens_in": 1, "tokens_out": 1},
        }

    monkeypatch.setattr("app.api.admin_connectivity.LLMRouter.route_and_generate", fake_route_and_generate)

    client = TestClient(app)
    resp = client.post(
        "/api/admin/connectivity/test",
        json={
            "target": "llm",
            "llm_provider": "openai",
            "llm_api_key": "sk-test",
            "llm_model": "gpt-4o-mini",
            "llm_base_url": "https://api.openai.com/v1",
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is False
    assert payload["target"] == "llm"
    assert payload["detail"]["actual_provider"] == "stub"
