import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.embedding_client import EmbeddingClient


def test_embedding_client_uses_runtime_config(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class _DummyResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": [{"embedding": [0.1, -0.1, 0.3]}]}

    def fake_post(url: str, headers: dict, json: dict, timeout: float):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _DummyResponse()

    monkeypatch.setattr("worker.embedding_client.requests.post", fake_post)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)

    client = EmbeddingClient()
    vec = client.embed_text(
        "runtime embedding",
        runtime_config={
            "embedding_provider": "openai",
            "embedding_api_key": "Bearer emb-runtime-key",
            "embedding_model": "text-embedding-3-small",
            "embedding_base_url": "https://emb.example.com/v1",
        },
    )

    assert captured["url"] == "https://emb.example.com/v1/embeddings"
    assert captured["headers"]["Authorization"] == "Bearer emb-runtime-key"
    assert captured["json"]["model"] == "text-embedding-3-small"
    assert isinstance(vec, list) and len(vec) == 3
