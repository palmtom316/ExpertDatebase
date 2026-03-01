import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.services.retrieval_eval import evaluate_retrieval_samples


def test_evaluate_retrieval_hit_and_mrr() -> None:
    samples = [
        {"query": "电容器", "expected_doc_id": "doc_a", "expected_pages": [11]},
        {"query": "真空断路器", "expected_doc_id": "doc_a", "expected_pages": [7]},
        {"query": "不存在", "expected_doc_id": "doc_a", "expected_pages": [99]},
    ]

    def fake_search(sample: dict) -> list[dict]:
        q = sample["query"]
        if q == "电容器":
            return [
                {"payload": {"doc_id": "doc_a", "page_start": 11, "page_end": 11}},
                {"payload": {"doc_id": "doc_a", "page_start": 20, "page_end": 20}},
            ]
        if q == "真空断路器":
            return [
                {"payload": {"doc_id": "doc_a", "page_start": 3, "page_end": 3}},
                {"payload": {"doc_id": "doc_a", "page_start": 7, "page_end": 7}},
            ]
        return [{"payload": {"doc_id": "doc_a", "page_start": 1, "page_end": 1}}]

    result = evaluate_retrieval_samples(samples=samples, search_fn=fake_search, top_k=10)
    assert result["query_count"] == 3
    assert abs(result["hit_at_5"] - (2 / 3)) < 1e-9
    assert abs(result["hit_at_10"] - (2 / 3)) < 1e-9
    # RR = 1 + 1/2 + 0
    assert abs(result["mrr"] - (1.5 / 3)) < 1e-9


def test_evaluate_retrieval_relevant_any() -> None:
    samples = [
        {
            "query": "11.4.1",
            "relevant_any": [
                {"doc_id": "doc_a", "page": 12},
                {"doc_id": "doc_b", "chapter_id": "ch_8"},
            ],
        }
    ]

    def fake_search(_: dict) -> list[dict]:
        return [
            {"payload": {"doc_id": "doc_c", "page_start": 1, "page_end": 1}},
            {"payload": {"doc_id": "doc_b", "chapter_id": "ch_8", "page_start": 88, "page_end": 90}},
        ]

    result = evaluate_retrieval_samples(samples=samples, search_fn=fake_search, top_k=10)
    assert abs(result["hit_at_5"] - 1.0) < 1e-9
    assert abs(result["mrr"] - 0.5) < 1e-9

