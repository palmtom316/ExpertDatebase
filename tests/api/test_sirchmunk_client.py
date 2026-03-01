import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.services.retrieval.sparse.sirchmunk_client import SirchmunkClient


class _Resp:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("http failed")

    def json(self) -> dict:
        return self._payload


def test_sirchmunk_client_normalizes_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    client = SirchmunkClient(base_url="http://sirchmunk.test")

    def fake_post(url: str, json: dict, timeout: float):  # noqa: ARG001
        return _Resp(
            200,
            {
                "hits": [
                    {"doc_id": "doc_1", "page_no": 2, "excerpt": "line", "score": 8.1},
                ]
            },
        )

    monkeypatch.setattr("app.services.retrieval.sparse.sirchmunk_client.requests.post", fake_post)
    out = client.search("11.4.1", top_n=20)
    assert out[0]["source"] == "sirchmunk"
    assert out[0]["doc_id"] == "doc_1"


def test_sirchmunk_client_circuit_breaker(monkeypatch: pytest.MonkeyPatch) -> None:
    client = SirchmunkClient(base_url="http://sirchmunk.test", fail_threshold=2, cooldown_seconds=999)

    def fake_post(url: str, json: dict, timeout: float):  # noqa: ARG001
        raise RuntimeError("down")

    monkeypatch.setattr("app.services.retrieval.sparse.sirchmunk_client.requests.post", fake_post)
    with pytest.raises(RuntimeError):
        client.search("a")
    with pytest.raises(RuntimeError):
        client.search("b")
    with pytest.raises(RuntimeError):
        client.search("c")
