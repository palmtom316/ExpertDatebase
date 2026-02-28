import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.mineru_client import MinerUClient


def test_mineru_client_uses_runtime_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    class _DummyResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "pages": [
                    {
                        "page_no": 1,
                        "blocks": [{"type": "paragraph", "text": "runtime mineru"}],
                        "tables": [],
                    }
                ]
            }

    def fake_post(url: str, headers: dict, files: dict, timeout: float):
        captured["url"] = url
        captured["headers"] = headers
        return _DummyResponse()

    monkeypatch.setattr("worker.mineru_client.requests.post", fake_post)

    client = MinerUClient()
    out = client.parse_pdf(
        b"%PDF-1.4",
        runtime_config={
            "mineru_api_base": "https://mineru.example.com",
            "mineru_api_key": "mineru-key",
        },
    )

    assert captured["url"] == "https://mineru.example.com/parse"
    assert captured["headers"]["Authorization"] == "Bearer mineru-key"
    assert out["pages"][0]["blocks"][0]["text"] == "runtime mineru"
