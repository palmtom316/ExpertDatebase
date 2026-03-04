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
from app.services.search_service import InMemoryQdrantRepo, QdrantHttpRepo, SimpleEmbeddingClient, hybrid_search  # noqa: E402


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

    def test_hybrid_search_allows_qdrant_keyword_fallback_by_default(self) -> None:
        class _RepoQdrantKeyword(QdrantHttpRepo):
            def __init__(self) -> None:
                super().__init__(endpoint="http://localhost:6333")

            def search(self, query_vector, filter_json=None, limit=5):  # noqa: ARG002
                return []

            def keyword_search(self, query_text, filter_json=None, limit=20):  # noqa: ARG002
                return [
                    {
                        "id": "kw_default",
                        "score": 9.0,
                        "payload": {
                            "doc_id": "doc_kw",
                            "version_id": "ver_kw",
                            "doc_name": "kw.pdf",
                            "page_start": 8,
                            "page_end": 8,
                            "excerpt": "8.1.1 设备安装应符合设计要求。",
                            "chunk_text": "8.1.1 设备安装应符合设计要求。",
                        },
                    }
                ]

        old = dict(os.environ)
        os.environ["HYBRID_KEYWORD_ENABLED"] = "1"
        os.environ.pop("ENABLE_QDRANT_SCROLL_KEYWORD", None)
        os.environ["ENABLE_RERANK"] = "0"
        try:
            result = hybrid_search(
                question="设备安装要求",
                repo=_RepoQdrantKeyword(),
                entity_index=DummyEntityIndex(),
                top_k=3,
            )
            self.assertEqual(len(result["citations"]), 1)
            self.assertEqual(result["citations"][0].get("doc_name"), "kw.pdf")
            self.assertEqual((result.get("debug") or {}).get("route_counts", {}).get("keyword"), 1)
        finally:
            os.environ.clear()
            os.environ.update(old)

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

    def test_embedding_stub_adapts_to_qdrant_vector_size_when_unpinned(self) -> None:
        client = SimpleEmbeddingClient()
        fake_resp = Mock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = {
            "result": {
                "config": {
                    "params": {
                        "vectors": {
                            "text_embedding": {"size": 4096, "distance": "Cosine"}
                        }
                    }
                }
            }
        }
        old = dict(os.environ)
        os.environ["VECTORDB_ENDPOINT"] = "http://qdrant:6333"
        os.environ["QDRANT_COLLECTION"] = "chunks_v1"
        os.environ["QDRANT_VECTOR_NAME"] = "text_embedding"
        os.environ.pop("EMBEDDING_DIM", None)
        try:
            with patch("app.services.search_service.requests.get", return_value=fake_resp):
                vec = client.embed_text("测试向量维度")
            self.assertEqual(len(vec), 4096)
        finally:
            os.environ.clear()
            os.environ.update(old)

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

    def test_hybrid_search_listing_query_expands_children_without_chapter_keyword(self) -> None:
        class _RepoParentChildren:
            def __init__(self) -> None:
                self.vector_called = False

            def search(self, query_vector, filter_json=None, limit=5):
                self.vector_called = True
                return []

            def keyword_search(self, query_text, filter_json=None, limit=20):
                must = (filter_json or {}).get("must") or []
                has_clause_constraint = any(item.get("key") in {"clause_id", "clause_no"} for item in must)
                if has_clause_constraint:
                    return []
                return [
                    {
                        "id": "pc_431",
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
                        "id": "pc_432",
                        "score": 8.8,
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
                ]

            def delete_by_version(self, version_id: str):
                return None

        repo = _RepoParentChildren()
        old = dict(os.environ)
        os.environ["ENABLE_RERANK"] = "0"
        os.environ["HYBRID_POST_KEYWORD_BOOST"] = "0"
        try:
            result = hybrid_search(
                question="请列出 4.3 包括哪些要求",
                repo=repo,
                entity_index=DummyEntityIndex(),
                top_k=5,
            )
            self.assertFalse(repo.vector_called)
            self.assertEqual(result["debug"]["route_counts"]["chapter_prefix"], 2)
            clause_ids = [str(c.get("clause_id") or "") for c in result["citations"]]
            self.assertIn("4.3.1", clause_ids)
            self.assertIn("4.3.2", clause_ids)
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

    def test_hybrid_search_table_query_detects_numeric_unit_pattern(self) -> None:
        repo = InMemoryQdrantRepo()
        repo.upsert(
            point_id="plain",
            vector=[0.1, 0.2],
            payload={
                "doc_id": "doc_a",
                "version_id": "ver_a",
                "doc_name": "spec.pdf",
                "page_start": 3,
                "page_end": 3,
                "excerpt": "设备绝缘试验要求。",
                "chunk_text": "设备绝缘试验要求。",
                "source_type": "text",
                "page_type": "other",
            },
        )
        repo.upsert(
            point_id="table-row",
            vector=[0.2, 0.1],
            payload={
                "doc_id": "doc_a",
                "version_id": "ver_a",
                "doc_name": "spec.pdf",
                "page_start": 5,
                "page_end": 5,
                "excerpt": "额定电压|110kV|主变",
                "chunk_text": "额定电压|110kV|主变",
                "source_type": "table_row",
                "page_type": "table",
                "val_voltage_kv": 110,
            },
        )

        old = dict(os.environ)
        os.environ["ENABLE_RERANK"] = "0"
        os.environ["HYBRID_KEYWORD_ENABLED"] = "0"
        os.environ["HYBRID_POST_KEYWORD_BOOST"] = "1"
        try:
            result = hybrid_search(
                question="110kV 主变额定电压",
                repo=repo,
                entity_index=DummyEntityIndex(),
                top_k=2,
            )
            self.assertEqual(result["citations"][0].get("source_type"), "table_row")
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_hybrid_search_table_sparse_filter_prefers_table_rows(self) -> None:
        class _RepoSparseFilter:
            def search(self, query_vector, filter_json=None, limit=5):
                return []

            def keyword_search(self, query_text, filter_json=None, limit=20):
                return []

            def delete_by_version(self, version_id: str):
                return None

        captured_filters: list[dict | None] = []

        class _FakePgBm25:
            def search(self, query_text, top_n=20, filters=None):
                captured_filters.append(filters)
                return []

        old = dict(os.environ)
        os.environ["ENABLE_RERANK"] = "0"
        os.environ["HYBRID_KEYWORD_ENABLED"] = "0"
        os.environ["ENABLE_PG_BM25"] = "1"
        os.environ["HYBRID_TABLE_QUERY_SPARSE_FILTER"] = "1"
        try:
            with patch("app.services.search_service.PgBM25SparseRetriever", return_value=_FakePgBm25()):
                hybrid_search(
                    question="请给出110kV参数",
                    repo=_RepoSparseFilter(),
                    entity_index=DummyEntityIndex(),
                    top_k=2,
                )
            self.assertTrue(captured_filters)
            must = (captured_filters[0] or {}).get("must") or []
            source_type = next(item for item in must if item.get("key") == "source_type")
            self.assertEqual((source_type.get("match") or {}).get("any"), ["table_row", "cross_page_table_row"])
        finally:
            os.environ.clear()
            os.environ.update(old)
    def test_hybrid_search_attaches_explanation_sibling_for_clause_route(self) -> None:
        class _RepoExplainSibling:
            def search(self, query_vector, filter_json=None, limit=5):
                return []

            def keyword_search(self, query_text, filter_json=None, limit=20):
                must = (filter_json or {}).get("must") or []
                is_explanation_lookup = any(
                    item.get("key") == "source_type" and (item.get("match") or {}).get("value") == "explanation"
                    for item in must
                )
                if is_explanation_lookup:
                    return [
                        {
                            "id": "exp-321",
                            "score": 7.5,
                            "payload": {
                                "doc_id": "doc_spec",
                                "version_id": "ver_spec",
                                "doc_name": "spec.pdf",
                                "page_start": 41,
                                "page_end": 41,
                                "excerpt": "3.2.1 条文说明：设备参数应满足运行要求。",
                                "chunk_text": "3.2.1 条文说明：设备参数应满足运行要求。",
                                "source_type": "explanation",
                                "clause_id": "3.2.1",
                            },
                        }
                    ]
                return [
                    {
                        "id": "clause-main",
                        "score": 9.0,
                        "payload": {
                            "doc_id": "doc_spec",
                            "version_id": "ver_spec",
                            "doc_name": "spec.pdf",
                            "page_start": 18,
                            "page_end": 18,
                            "excerpt": "3.2.1 试验电压应符合表3.2.1要求。",
                            "chunk_text": "3.2.1 试验电压应符合表3.2.1要求。",
                            "source_type": "text",
                            "clause_id": "3.2.1",
                        },
                    }
                ]

            def delete_by_version(self, version_id: str):
                return None

        old = dict(os.environ)
        os.environ["ENABLE_RERANK"] = "0"
        os.environ["HYBRID_POST_KEYWORD_BOOST"] = "0"
        os.environ["HYBRID_ATTACH_EXPLANATION"] = "1"
        try:
            result = hybrid_search(
                question="请给出 3.2.1 条原文",
                repo=_RepoExplainSibling(),
                entity_index=DummyEntityIndex(),
                top_k=3,
            )
            self.assertEqual(len(result["citations"]), 2)
            self.assertEqual(result["citations"][0].get("source_type"), "text")
            self.assertEqual(result["citations"][1].get("source_type"), "explanation")
            self.assertEqual(result["citations"][1].get("route"), "explanation_sibling")
            self.assertEqual(result["citations"][1].get("clause_id"), "3.2.1")
            stats = result["debug"]["explanation_attach"]
            self.assertEqual(stats["clause_candidates"], 1)
            self.assertEqual(stats["clause_lookups"], 1)
            self.assertEqual(stats["clause_hits"], 1)
            self.assertEqual(stats["attached"], 1)
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_hybrid_search_attaches_explanation_by_filter_when_excerpt_has_no_clause_id(self) -> None:
        repo = InMemoryQdrantRepo()
        repo.upsert(
            point_id="clause-431",
            vector=[0.1, 0.2],
            payload={
                "doc_id": "doc_spec",
                "version_id": "ver_spec",
                "doc_name": "spec.pdf",
                "page_start": 19,
                "page_end": 19,
                "excerpt": "4.3.1 绝缘油的验收与保管应符合下列规定。",
                "chunk_text": "4.3.1 绝缘油的验收与保管应符合下列规定。",
                "source_type": "text",
                "clause_id": "4.3.1",
            },
        )
        repo.upsert(
            point_id="exp-431",
            vector=[0.2, 0.1],
            payload={
                "doc_id": "doc_spec",
                "version_id": "ver_spec",
                "doc_name": "spec.pdf",
                "page_start": 47,
                "page_end": 47,
                "excerpt": "绝缘油管理工作的好坏，是保证设备质量的关键，应引起充分注意。",
                "chunk_text": "绝缘油管理工作的好坏，是保证设备质量的关键，应引起充分注意。",
                "source_type": "explanation",
                "clause_id": "4.3.1",
            },
        )

        old = dict(os.environ)
        os.environ["ENABLE_RERANK"] = "0"
        os.environ["HYBRID_POST_KEYWORD_BOOST"] = "0"
        os.environ["HYBRID_ATTACH_EXPLANATION"] = "1"
        try:
            result = hybrid_search(
                question="请给出 4.3.1 绝缘油验收与保管规定",
                repo=repo,
                entity_index=DummyEntityIndex(),
                top_k=3,
            )
            self.assertEqual(len(result["citations"]), 2)
            self.assertEqual(result["citations"][0].get("source_type"), "text")
            self.assertEqual(result["citations"][1].get("source_type"), "explanation")
            self.assertEqual(result["citations"][1].get("route"), "explanation_sibling")
            stats = result["debug"]["explanation_attach"]
            self.assertEqual(stats["attached"], 1)
            self.assertEqual(stats["clause_hits"], 1)
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_hybrid_search_doc_scoped_filter_keyword_fallback_for_natural_question(self) -> None:
        class _RepoDocScopedFallback:
            def search(self, query_vector, filter_json=None, limit=5):
                return []

            def keyword_search(self, query_text, filter_json=None, limit=20):
                return []

            def fetch_by_filter(self, filter_json=None, limit=20):
                return [
                    {
                        "id": "doc-hit-1",
                        "score": None,
                        "payload": {
                            "doc_id": "doc_spec",
                            "version_id": "ver_spec",
                            "doc_name": "spec.pdf",
                            "page_start": 19,
                            "page_end": 19,
                            "excerpt": "绝缘油的验收与保管应符合下列规定。",
                            "chunk_text": "绝缘油的验收与保管应符合下列规定，且应有试验记录。",
                            "source_type": "text",
                            "clause_id": "4.3.1",
                        },
                    }
                ]

            def delete_by_version(self, version_id: str):
                return None

        old = dict(os.environ)
        os.environ["ENABLE_RERANK"] = "0"
        os.environ["HYBRID_POST_KEYWORD_BOOST"] = "0"
        os.environ["HYBRID_KEYWORD_ENABLED"] = "0"
        try:
            result = hybrid_search(
                question="绝缘油的验收和保管应该服从什么规定",
                repo=_RepoDocScopedFallback(),
                entity_index=DummyEntityIndex(),
                top_k=3,
                search_filter={"must": [{"key": "doc_id", "match": {"value": "doc_spec"}}]},
            )
            self.assertGreaterEqual(len(result["citations"]), 1)
            self.assertEqual(result["citations"][0].get("doc_name"), "spec.pdf")
            self.assertEqual(result["citations"][0].get("route"), "filter_keyword")
            self.assertEqual(result["debug"]["route_counts"]["filter_keyword"], 1)
        finally:
            os.environ.clear()
            os.environ.update(old)


if __name__ == "__main__":
    unittest.main()
