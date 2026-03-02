import sys
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.qdrant_repo import QdrantHttpRepo


class _Resp:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


def test_worker_qdrant_upsert_recovers_from_vector_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"put": [], "delete": []}

    def fake_put(url: str, json: dict, timeout: float):
        calls["put"].append(url)
        if url.endswith("/collections/chunks_v1/points?wait=true"):
            # first upsert fails, second upsert (after recreate) succeeds
            if sum(1 for u in calls["put"] if u.endswith("/points?wait=true")) == 1:
                return _Resp(400, text="wrong vector size: expected dim: 8, got 1024")
            return _Resp(200, text='{"result":{"status":"ok"}}')
        if url.endswith("/collections/chunks_v1"):
            return _Resp(200, text='{"result":true}')
        raise AssertionError(f"unexpected PUT url: {url}")

    def fake_delete(url: str, timeout: float):
        calls["delete"].append(url)
        return _Resp(200, text='{"result":true}')

    monkeypatch.setattr("worker.qdrant_repo.requests.put", fake_put)
    monkeypatch.setattr("worker.qdrant_repo.requests.delete", fake_delete)

    repo = QdrantHttpRepo(endpoint="http://qdrant:6333", collection="chunks_v1", vector_name="text_embedding")
    repo._collection_ready = True  # emulate stale in-memory state

    repo.upsert(
        point_id="c1",
        vector=[0.1] * 1024,
        payload={"doc_name": "demo.pdf"},
    )

    assert "http://qdrant:6333/collections/chunks_v1" in calls["delete"]
    assert calls["put"].count("http://qdrant:6333/collections/chunks_v1/points?wait=true") == 2


def test_worker_qdrant_upsert_retries_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"put": 0}

    def fake_put(url: str, json: dict, timeout: float):
        calls["put"] += 1
        if url.endswith("/collections/chunks_v1/points?wait=true") and calls["put"] == 2:
            raise requests.Timeout("read timeout")
        return _Resp(200, text='{"result":{"status":"ok"}}')

    monkeypatch.setattr("worker.qdrant_repo.requests.put", fake_put)

    repo = QdrantHttpRepo(endpoint="http://qdrant:6333", collection="chunks_v1", vector_name="text_embedding")

    repo.upsert(
        point_id="c2",
        vector=[0.1] * 1024,
        payload={"doc_name": "demo.pdf"},
    )

    # one put for ensure-collection + two puts for upsert (first timeout, second success)
    assert calls["put"] == 3
