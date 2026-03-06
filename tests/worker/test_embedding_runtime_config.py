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
            "embedding_provider": "siliconflow",
            "embedding_api_key": "Bearer emb-runtime-key",
            "embedding_model": "Qwen/Qwen3-Embedding-8B",
            "embedding_base_url": "https://api.siliconflow.cn/v1",
            "embedding_dimensions": "1024",
        },
    )

    assert captured["url"] == "https://api.siliconflow.cn/v1/embeddings"
    assert captured["headers"]["Authorization"] == "Bearer emb-runtime-key"
    assert captured["json"]["model"] == "Qwen/Qwen3-Embedding-8B"
    assert captured["json"]["dimensions"] == 1024
    assert isinstance(vec, list) and len(vec) == 3


def test_embedding_client_batches_texts(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class _DummyResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "data": [
                    {"embedding": [0.1, -0.1, 0.3]},
                    {"embedding": [0.2, -0.2, 0.4]},
                ]
            }

    def fake_post(url: str, headers: dict, json: dict, timeout: float):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _DummyResponse()

    monkeypatch.setattr("worker.embedding_client.requests.post", fake_post)

    client = EmbeddingClient()
    vectors = client.embed_texts(
        ["first", "second"],
        runtime_config={
            "embedding_provider": "siliconflow",
            "embedding_api_key": "emb-runtime-key",
            "embedding_model": "Qwen/Qwen3-Embedding-8B",
            "embedding_base_url": "https://api.siliconflow.cn/v1",
        },
    )

    meta = client.pop_last_call_meta()

    assert captured["json"]["input"] == ["first", "second"]
    assert len(vectors) == 2
    assert meta["item_count"] == 2
    assert meta["request_count"] == 1


def test_embedding_stub_dim_follows_qdrant_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "result": {
                    "config": {
                        "params": {
                            "vectors": {
                                "text_embedding": {"size": 4096},
                            }
                        }
                    }
                }
            }

    calls = {"n": 0}

    def fake_get(url: str, timeout: float):  # noqa: ARG001
        calls["n"] += 1
        return _Resp()

    monkeypatch.delenv("EMBEDDING_DIM", raising=False)
    monkeypatch.setenv("VECTORDB_ENDPOINT", "http://qdrant:6333")
    monkeypatch.setenv("QDRANT_COLLECTION", "chunks_v1")
    monkeypatch.setenv("QDRANT_VECTOR_NAME", "text_embedding")
    monkeypatch.setattr("worker.embedding_client.requests.get", fake_get)

    client = EmbeddingClient()
    vec1 = client.embed_text("first")
    vec2 = client.embed_text("second")

    assert len(vec1) == 4096
    assert len(vec2) == 4096
    assert calls["n"] == 1


def test_embedding_dim_env_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_get(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("should not call qdrant when EMBEDDING_DIM is pinned")

    monkeypatch.setenv("EMBEDDING_DIM", "128")
    monkeypatch.setattr("worker.embedding_client.requests.get", fail_get)

    client = EmbeddingClient()
    vec = client.embed_text("pinned")
    assert len(vec) == 128
