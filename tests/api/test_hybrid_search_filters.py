import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import os

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.services.filter_parser import parse_filter_spec  # noqa: E402
from app.services.search_service import InMemoryQdrantRepo, SimpleEmbeddingClient, hybrid_search  # noqa: E402


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

    def test_embedding_fallback_to_stub_when_openai_returns_403(self) -> None:
        client = SimpleEmbeddingClient(dim=16)
        runtime = {
            "embedding_provider": "openai",
            "embedding_api_key": "sk-test",
            "embedding_base_url": "https://api.siliconflow.cn/v1",
            "embedding_model": "Qwen/Qwen3-Embedding-8B",
        }

        fake_resp = Mock()
        fake_resp.raise_for_status.side_effect = RuntimeError("403 Forbidden")

        with patch("app.services.search_service.requests.post", return_value=fake_resp):
            vec = client.embed_text("测试文本", runtime_config=runtime)

        self.assertIsInstance(vec, list)
        self.assertEqual(len(vec), 16)
        self.assertTrue(any(abs(x) > 0 for x in vec))

    def test_hybrid_search_post_keyword_boost_promotes_direct_match(self) -> None:
        class _RepoForBoost:
            def search(self, query_vector, filter_json=None, limit=5):
                return [
                    {
                        "id": "a",
                        "score": 0.95,
                        "payload": {
                            "doc_name": "spec.pdf",
                            "doc_id": "d1",
                            "version_id": "v1",
                            "page_start": 20,
                            "page_end": 20,
                            "excerpt": "本章节说明设备试验要求。",
                            "chunk_text": "本章节说明设备试验要求。",
                        },
                    },
                    {
                        "id": "b",
                        "score": 0.70,
                        "payload": {
                            "doc_name": "spec.pdf",
                            "doc_id": "d1",
                            "version_id": "v1",
                            "page_start": 2,
                            "page_end": 2,
                            "excerpt": "1.0.2 本标准适用范围为电气装置安装工程交接试验。",
                            "chunk_text": "1.0.2 本标准适用范围为电气装置安装工程交接试验。",
                        },
                    },
                ]

            def keyword_search(self, query_text, filter_json=None, limit=20):
                return []

            def delete_by_version(self, version_id: str):
                return None

        old = dict(os.environ)
        os.environ["ENABLE_RERANK"] = "0"
        os.environ["HYBRID_KEYWORD_ENABLED"] = "0"
        os.environ["HYBRID_POST_KEYWORD_BOOST"] = "1"
        try:
            result = hybrid_search(
                question="本标准适用范围",
                repo=_RepoForBoost(),
                entity_index=DummyEntityIndex(),
                top_k=2,
            )
            self.assertEqual(len(result["citations"]), 2)
            self.assertEqual(result["citations"][0].get("page_start"), 2)
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_parse_filter_spec_multi_clause_uses_any(self) -> None:
        f, sparse_query, _ = parse_filter_spec("请对比 3.0.1 与 3.0.2 的要求", DummyEntityIndex())
        self.assertIsNotNone(f)
        must = f["must"]
        clause_no = next(item for item in must if item["key"] == "clause_no")
        any_values = (clause_no.get("match") or {}).get("any") or []
        self.assertIn("3.0.1", any_values)
        self.assertIn("3.0.2", any_values)
        self.assertIn("3.0.1", sparse_query)
        self.assertIn("3.0.2", sparse_query)

    def test_parse_filter_spec_adds_mandatory_filter(self) -> None:
        f, sparse_query, _ = parse_filter_spec("请给出 4.12.1(3) 强制性条文，必须执行", DummyEntityIndex())
        self.assertIsNotNone(f)
        must = f["must"]
        clause_no = next(item for item in must if item["key"] == "clause_no")
        self.assertIn("4.12.1(3)", (clause_no.get("match") or {}).get("any", []))
        mandatory = next(item for item in must if item["key"] == "is_mandatory")
        self.assertTrue((mandatory.get("match") or {}).get("value"))
        self.assertIn("强制性条文", sparse_query)

    def test_hybrid_search_clause_exact_route_prioritizes_exact_filter(self) -> None:
        class _RepoClauseOnly:
            def __init__(self) -> None:
                self.vector_called = False

            def search(self, query_vector, filter_json=None, limit=5):
                self.vector_called = True
                return []

            def keyword_search(self, query_text, filter_json=None, limit=20):
                must = (filter_json or {}).get("must") or []
                has_clause = any(
                    item.get("key") == "clause_id" and "3.2.1" in ((item.get("match") or {}).get("any") or [])
                    for item in must
                )
                if not has_clause:
                    return []
                return [
                    {
                        "id": "clause-hit",
                        "score": 8.0,
                        "payload": {
                            "doc_id": "doc_spec",
                            "version_id": "ver_spec",
                            "doc_name": "spec.pdf",
                            "page_start": 18,
                            "page_end": 18,
                            "excerpt": "3.2.1 试验电压应符合表3.2.1要求。",
                            "chunk_text": "3.2.1 试验电压应符合表3.2.1要求。",
                            "clause_id": "3.2.1",
                        },
                    }
                ]

            def delete_by_version(self, version_id: str):
                return None

        repo = _RepoClauseOnly()
        old = dict(os.environ)
        os.environ["ENABLE_RERANK"] = "0"
        os.environ["HYBRID_POST_KEYWORD_BOOST"] = "0"
        try:
            result = hybrid_search(
                question="请给出 3.2.1 条原文",
                repo=repo,
                entity_index=DummyEntityIndex(),
                top_k=3,
            )
            self.assertFalse(repo.vector_called)
            self.assertEqual(result["debug"]["route_counts"]["clause_exact"], 1)
            self.assertEqual(result["citations"][0].get("clause_id"), "3.2.1")
            self.assertEqual(result["citations"][0].get("route"), "clause_exact")
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_hybrid_search_chapter_prefix_route_expands_to_sub_clauses(self) -> None:
        class _RepoChapterPrefix:
            def __init__(self) -> None:
                self.vector_called = False

            def search(self, query_vector, filter_json=None, limit=5):
                self.vector_called = True
                return []

            def keyword_search(self, query_text, filter_json=None, limit=20):
                return [
                    {
                        "id": "h431",
                        "score": 9.0,
                        "payload": {
                            "doc_id": "doc_spec",
                            "version_id": "ver_spec",
                            "doc_name": "spec.pdf",
                            "page_start": 19,
                            "page_end": 19,
                            "excerpt": "4.3.1 绝缘油的验收与保管",
                            "chunk_text": "4.3.1 绝缘油的验收与保管",
                            "clause_id": "4.3.1",
                        },
                    },
                    {
                        "id": "h432",
                        "score": 8.5,
                        "payload": {
                            "doc_id": "doc_spec",
                            "version_id": "ver_spec",
                            "doc_name": "spec.pdf",
                            "page_start": 20,
                            "page_end": 20,
                            "excerpt": "4.3.2 绝缘油处理应符合相关规定",
                            "chunk_text": "4.3.2 绝缘油处理应符合相关规定",
                            "clause_id": "4.3.2",
                        },
                    },
                    {
                        "id": "h441",
                        "score": 8.0,
                        "payload": {
                            "doc_id": "doc_spec",
                            "version_id": "ver_spec",
                            "doc_name": "spec.pdf",
                            "page_start": 24,
                            "page_end": 24,
                            "excerpt": "4.4.1 干燥处理",
                            "chunk_text": "4.4.1 干燥处理",
                            "clause_id": "4.4.1",
                        },
                    },
                ]

            def delete_by_version(self, version_id: str):
                return None

        repo = _RepoChapterPrefix()
        old = dict(os.environ)
        os.environ["ENABLE_RERANK"] = "0"
        os.environ["HYBRID_POST_KEYWORD_BOOST"] = "0"
        try:
            result = hybrid_search(
                question="请总结 GB20148-2010 第4.3章 绝缘油处理要求",
                repo=repo,
                entity_index=DummyEntityIndex(),
                top_k=5,
            )
            self.assertFalse(repo.vector_called)
            self.assertEqual(result["debug"]["route_counts"]["chapter_prefix"], 2)
            clause_ids = [str(c.get("clause_id") or "") for c in result["citations"]]
            self.assertIn("4.3.1", clause_ids)
            self.assertIn("4.3.2", clause_ids)
            self.assertNotIn("4.4.1", clause_ids)
            self.assertTrue(all(str(c.get("route") or "") == "chapter_prefix" for c in result["citations"]))
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_hybrid_search_chapter_prefix_ignores_standard_number_suffix_false_positive(self) -> None:
        class _RepoFalsePositive:
            def search(self, query_vector, filter_json=None, limit=5):
                return []

            def keyword_search(self, query_text, filter_json=None, limit=20):
                return [
                    {
                        "id": "good",
                        "score": 7.0,
                        "payload": {
                            "doc_id": "doc_spec",
                            "version_id": "ver_spec",
                            "doc_name": "spec.pdf",
                            "page_start": 19,
                            "page_end": 19,
                            "excerpt": "4.3 绝缘油处理。",
                            "chunk_text": "4.3 绝缘油处理。",
                            "clause_id": "4.3",
                        },
                    },
                    {
                        "id": "bad",
                        "score": 10.0,
                        "payload": {
                            "doc_id": "doc_spec",
                            "version_id": "ver_spec",
                            "doc_name": "spec.pdf",
                            "page_start": 31,
                            "page_end": 31,
                            "excerpt": "《电力变压器第3部分》GB1094.3。",
                            "chunk_text": "《电力变压器第3部分》GB1094.3。",
                            "clause_id": None,
                        },
                    },
                ]

            def delete_by_version(self, version_id: str):
                return None

        old = dict(os.environ)
        os.environ["ENABLE_RERANK"] = "0"
        os.environ["HYBRID_POST_KEYWORD_BOOST"] = "0"
        try:
            result = hybrid_search(
                question="请总结第4.3章要求",
                repo=_RepoFalsePositive(),
                entity_index=DummyEntityIndex(),
                top_k=5,
            )
            excerpts = [str(c.get("excerpt") or "") for c in result["citations"]]
            assert any("4.3 绝缘油处理" in e for e in excerpts)
            assert not any("GB1094.3" in e for e in excerpts)
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_hybrid_search_table_priority_boosts_table_rows(self) -> None:
        class _RepoTableBoost:
            def search(self, query_vector, filter_json=None, limit=5):
                return [
                    {
                        "id": "plain",
                        "score": 0.9,
                        "payload": {
                            "doc_id": "doc_a",
                            "version_id": "ver_a",
                            "doc_name": "spec.pdf",
                            "page_start": 3,
                            "page_end": 3,
                            "excerpt": "3.0.9 设备绝缘试验要求。",
                            "chunk_text": "3.0.9 设备绝缘试验要求。",
                            "source_type": "text",
                            "page_type": "other",
                        },
                    },
                    {
                        "id": "table-row",
                        "score": 0.5,
                        "payload": {
                            "doc_id": "doc_a",
                            "version_id": "ver_a",
                            "doc_name": "spec.pdf",
                            "page_start": 5,
                            "page_end": 5,
                            "excerpt": "表3.0.9 设备电压等级与兆欧表选用关系 | <500 | 500 | 100",
                            "chunk_text": "表3.0.9 设备电压等级与兆欧表选用关系 | <500 | 500 | 100",
                            "source_type": "table_row",
                            "page_type": "power_param_table",
                        },
                    },
                ]

            def keyword_search(self, query_text, filter_json=None, limit=20):
                return []

            def delete_by_version(self, version_id: str):
                return None

        old = dict(os.environ)
        os.environ["ENABLE_RERANK"] = "0"
        os.environ["HYBRID_KEYWORD_ENABLED"] = "0"
        os.environ["HYBRID_POST_KEYWORD_BOOST"] = "1"
        try:
            result = hybrid_search(
                question="表3.0.9 兆欧表选型",
                repo=_RepoTableBoost(),
                entity_index=DummyEntityIndex(),
                top_k=2,
            )
            self.assertEqual(result["citations"][0].get("source_type"), "table_row")
        finally:
            os.environ.clear()
            os.environ.update(old)


if __name__ == "__main__":
    unittest.main()
