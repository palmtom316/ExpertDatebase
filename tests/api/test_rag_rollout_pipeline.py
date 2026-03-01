import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.services import search_service
from app.services.search_service import hybrid_search


class DummyEntityIndex:
    def match_names(self, kind: str, question: str) -> list[str]:
        return []

    def get_id(self, kind: str, name: str) -> str | None:
        return None


class DummyRepo:
    def search(self, query_vector, filter_json=None, limit=5):
        return [
            {
                "id": "dense-1",
                "score": 0.8,
                "payload": {
                    "doc_id": "dense_doc",
                    "doc_name": "dense.pdf",
                    "page_start": 1,
                    "page_end": 1,
                    "excerpt": "dense evidence",
                    "chunk_text": "dense evidence",
                },
            }
        ]

    def keyword_search(self, query_text, filter_json=None, limit=20):
        return []

    def delete_by_version(self, version_id: str):
        return None


def test_hybrid_search_uses_multiroute_fusion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_SIRCHMUNK", "1")
    monkeypatch.setenv("ENABLE_STRUCTURED_LOOKUP", "1")
    monkeypatch.setenv("ENABLE_YOUTU_GRAPHRAG", "1")
    monkeypatch.setenv("ENABLE_RERANK", "0")
    monkeypatch.setenv("ENABLE_PG_BM25", "0")

    monkeypatch.setattr(
        search_service.SirchmunkClient,
        "search",
        lambda self, query_text, top_n=200: [
            {"doc_id": "sparse_doc", "page_no": 2, "excerpt": "sparse evidence", "score": 7.0, "source": "sirchmunk"}
        ],
    )
    monkeypatch.setattr(
        search_service.StructuredLookupService,
        "lookup",
        lambda self, question, top_n=50: [
            {"doc_id": "structured_doc", "page_no": 3, "excerpt": "structured evidence", "score": 9.0, "source": "structured"}
        ],
    )
    monkeypatch.setattr(
        search_service.GraphRAGClient,
        "search",
        lambda self, question, top_n=50: [
            {"doc_id": "graph_doc", "page_no": 4, "excerpt": "graph evidence", "score": 6.0, "source": "graphrag"}
        ],
    )

    out = hybrid_search(
        question="条款11.4.1和证书ZJ-A-2024-009分别关联谁",
        repo=DummyRepo(),
        entity_index=DummyEntityIndex(),
        top_k=6,
    )

    docs = {str((c or {}).get("doc_name") or "") for c in out["citations"]}
    assert "dense.pdf" in docs
    # Sparse/structured/graphrag candidates may not have doc_name but should carry source route.
    routes = {str((c or {}).get("route") or "") for c in out["citations"]}
    assert "sparse" in routes
    assert "structured" in routes
    assert "graphrag" in routes
    assert "debug" in out
    assert out["debug"]["route_counts"]["dense"] >= 1


def test_hybrid_search_rolls_back_when_sparse_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_SIRCHMUNK", "1")
    monkeypatch.setenv("ENABLE_STRUCTURED_LOOKUP", "0")
    monkeypatch.setenv("ENABLE_YOUTU_GRAPHRAG", "0")
    monkeypatch.setenv("ENABLE_RERANK", "0")

    def _raise(*args, **kwargs):
        raise RuntimeError("sidecar down")

    monkeypatch.setattr(search_service.SirchmunkClient, "search", _raise)

    out = hybrid_search(
        question="sidecar 故障回滚",
        repo=DummyRepo(),
        entity_index=DummyEntityIndex(),
        top_k=3,
    )

    assert len(out["hits"]) >= 1
    assert out["debug"]["degraded_routes"]["sparse"] == "sidecar down"
