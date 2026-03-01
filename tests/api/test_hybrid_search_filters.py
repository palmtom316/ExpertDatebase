import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.services.filter_parser import parse_filter_spec  # noqa: E402
from app.services.search_service import InMemoryQdrantRepo, hybrid_search  # noqa: E402


class DummyEntityIndex:
    def __init__(self) -> None:
        self.ids = {"张建国": "p:1001"}

    def match_names(self, kind: str, question: str) -> list[str]:
        return [n for n in self.ids if n in question]

    def get_id(self, kind: str, name: str) -> str | None:
        return self.ids.get(name)


class TestHybridSearchFilters(unittest.TestCase):
    def test_parse_filter_spec_builds_must_filters(self) -> None:
        f, sparse_query, dense_query = parse_filter_spec("张建国项目经理110kV且合同金额5000万", DummyEntityIndex())
        self.assertIsNotNone(f)
        keys = {x["key"] for x in f["must"]}
        self.assertIn("val_voltage_kv", keys)
        self.assertIn("val_contract_amount_w", keys)
        self.assertIn("entity_person_ids", keys)
        self.assertIn("rel_person_role", keys)
        self.assertIn("张建国", sparse_query)
        self.assertIn("110kV", dense_query)

    def test_hybrid_search_returns_citations(self) -> None:
        repo = InMemoryQdrantRepo()
        repo.upsert(
            point_id="ck1",
            vector=[0.1, 0.2],
            payload={
                "doc_id": "doc_a",
                "version_id": "ver_a",
                "doc_name": "demo.pdf",
                "page_start": 3,
                "page_end": 3,
                "excerpt": "张建国担任项目经理",
                "entity_person_ids": ["p:1001"],
                "rel_person_role": ["p:1001|项目经理"],
                "val_voltage_kv": 110,
                "val_contract_amount_w": 6000,
            },
        )

        result = hybrid_search(
            question="张建国项目经理110kV且合同金额5000万",
            repo=repo,
            entity_index=DummyEntityIndex(),
            top_k=3,
        )
        self.assertGreater(len(result["citations"]), 0)
        c = result["citations"][0]
        self.assertIn("doc_name", c)
        self.assertIn("page_start", c)
        self.assertIn("excerpt", c)

    def test_hybrid_search_applies_extra_search_filter(self) -> None:
        repo = InMemoryQdrantRepo()
        repo.upsert(
            point_id="ck_doc_a",
            vector=[0.1, 0.2],
            payload={
                "doc_id": "doc_a",
                "version_id": "ver_a",
                "doc_name": "a.pdf",
                "page_start": 1,
                "page_end": 1,
                "excerpt": "电容器章节A",
            },
        )
        repo.upsert(
            point_id="ck_doc_b",
            vector=[0.2, 0.3],
            payload={
                "doc_id": "doc_b",
                "version_id": "ver_b",
                "doc_name": "b.pdf",
                "page_start": 1,
                "page_end": 1,
                "excerpt": "电容器章节B",
            },
        )

        result = hybrid_search(
            question="电容器",
            repo=repo,
            entity_index=DummyEntityIndex(),
            top_k=10,
            search_filter={"must": [{"key": "version_id", "match": {"value": "ver_b"}}]},
        )
        self.assertEqual(len(result["citations"]), 1)
        self.assertEqual(result["citations"][0].get("doc_name"), "b.pdf")

    def test_hybrid_search_uses_keyword_recall_when_vector_empty(self) -> None:
        class _RepoWithKeyword:
            def search(self, query_vector, filter_json=None, limit=5):
                return []

            def keyword_search(self, query_text, filter_json=None, limit=20):
                return [
                    {
                        "id": "kw1",
                        "score": 10.0,
                        "payload": {
                            "doc_name": "spec.pdf",
                            "page_start": 11,
                            "page_end": 11,
                            "excerpt": "11.4.1 串联电容补偿装置",
                            "chunk_text": "11.4.1 串联电容补偿装置",
                        },
                    }
                ]

            def delete_by_version(self, version_id: str):
                return None

        result = hybrid_search(
            question="11.4.1 串联电容补偿装置",
            repo=_RepoWithKeyword(),
            entity_index=DummyEntityIndex(),
            top_k=5,
        )
        self.assertEqual(len(result["citations"]), 1)
        self.assertEqual(result["citations"][0].get("doc_name"), "spec.pdf")


if __name__ == "__main__":
    unittest.main()
