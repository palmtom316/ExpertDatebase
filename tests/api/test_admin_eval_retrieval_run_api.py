import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.main import app


class _DummyEntityIndex:
    pass


def test_admin_retrieval_eval_run_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    dataset = tmp_path / "retrieval_eval.jsonl"
    dataset.write_text(
        json.dumps({"query": "变压器安装有哪些规定", "expected_doc_id": "doc_1"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("app.api.admin_eval.create_search_repo_from_env", lambda: object())
    monkeypatch.setattr("app.api.admin_eval.build_entity_index_from_env", lambda: _DummyEntityIndex())

    def fake_hybrid_search(
        *,
        question: str,
        repo: object,
        entity_index: object,
        top_k: int,
        runtime_config: dict | None = None,
        search_filter: dict | None = None,
    ) -> dict:
        assert question
        assert top_k == 10
        assert (runtime_config or {}).get("embedding_provider") == "auto"
        return {
            "hits": [
                {
                    "payload": {
                        "doc_id": "doc_1",
                        "doc_name": "sample.pdf",
                        "page_start": 1,
                        "page_end": 1,
                        "excerpt": "命中证据",
                    }
                }
            ],
            "debug": {
                "route_counts": {"dense": 1},
                "degraded_routes": {"dense": "vector_dim_mismatch"},
                "embedding": {"used_stub": True},
            },
        }

    monkeypatch.setattr("app.api.admin_eval.hybrid_search", fake_hybrid_search)

    client = TestClient(app)
    resp = client.post(
        "/api/admin/eval/retrieval/run",
        json={"dataset_path": str(dataset), "top_k": 10, "embedding_provider": "auto"},
    )
    assert resp.status_code == 200
    payload = resp.json()["item"]
    assert payload["query_count"] == 1
    assert payload["hit_at_10"] == 1.0
    assert payload["mrr"] == 1.0
    assert payload["dataset"] == str(dataset.resolve())
    assert payload["search_debug"][0]["route_counts"]["dense"] == 1
    assert payload["search_debug"][0]["degraded_routes"]["dense"] == "vector_dim_mismatch"
    assert payload["allow_traffic"] == payload["release_gate"]["passed"]


def test_admin_retrieval_eval_dataset_not_found() -> None:
    client = TestClient(app)
    resp = client.post(
        "/api/admin/eval/retrieval/run",
        json={"dataset_path": "/tmp/not-exists-retrieval-eval.jsonl"},
    )
    assert resp.status_code == 404
    assert "retrieval dataset not found" in (resp.json().get("detail") or "")
