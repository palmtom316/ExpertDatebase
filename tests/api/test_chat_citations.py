import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.services.chat_orchestrator import chat_with_citations  # noqa: E402
from app.services.search_service import InMemoryQdrantRepo  # noqa: E402


class DummyEntityIndex:
    def match_names(self, kind: str, question: str) -> list[str]:
        return []

    def get_id(self, kind: str, name: str) -> str | None:
        return None


class TestChatCitations(unittest.TestCase):
    def test_chat_must_return_citations(self) -> None:
        repo = InMemoryQdrantRepo()
        repo.upsert(
            point_id="ck1",
            vector=[0.1, 0.2],
            payload={
                "doc_name": "demo.pdf",
                "page_start": 6,
                "page_end": 6,
                "excerpt": "合同金额为5000万元。",
            },
        )

        res = chat_with_citations(
            question="合同金额是多少？",
            repo=repo,
            entity_index=DummyEntityIndex(),
        )

        self.assertIn("answer", res)
        self.assertGreaterEqual(len(res["citations"]), 1)
        self.assertGreaterEqual(len(res["expandable_evidence"]), 1)
        self.assertIn("context_before", res["expandable_evidence"][0])
        self.assertIn("context_after", res["expandable_evidence"][0])

    def test_chat_clause_query_uses_fixed_sections_with_explanation(self) -> None:
        repo = InMemoryQdrantRepo()
        repo.upsert(
            point_id="ck_clause",
            vector=[0.1, 0.2],
            payload={
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
            point_id="ck_explain",
            vector=[0.2, 0.1],
            payload={
                "doc_name": "spec.pdf",
                "page_start": 47,
                "page_end": 47,
                "excerpt": "绝缘油管理工作的好坏，是保证设备质量的关键，应引起充分注意。",
                "chunk_text": "绝缘油管理工作的好坏，是保证设备质量的关键，应引起充分注意。",
                "source_type": "explanation",
                "route": "explanation_sibling",
                "clause_id": "4.3.1",
            },
        )

        res = chat_with_citations(
            question="绝缘油的验收和保管应该服从什么规定",
            repo=repo,
            entity_index=DummyEntityIndex(),
        )

        self.assertIn("条文规定：", res["answer"])
        self.assertIn("条文说明：", res["answer"])
        self.assertEqual(res["llm"]["model"], "clause-template-v1")

    def test_chat_clause_query_uses_fixed_sections_without_explanation(self) -> None:
        repo = InMemoryQdrantRepo()
        repo.upsert(
            point_id="ck_clause_only",
            vector=[0.1, 0.2],
            payload={
                "doc_name": "spec.pdf",
                "page_start": 19,
                "page_end": 19,
                "excerpt": "4.3.1 绝缘油的验收与保管应符合下列规定。",
                "chunk_text": "4.3.1 绝缘油的验收与保管应符合下列规定。",
                "source_type": "text",
                "clause_id": "4.3.1",
            },
        )

        res = chat_with_citations(
            question="请说明4.3.1规定",
            repo=repo,
            entity_index=DummyEntityIndex(),
        )

        self.assertIn("条文规定：", res["answer"])
        self.assertNotIn("条文说明：", res["answer"])
        self.assertEqual(res["llm"]["model"], "clause-template-v1")

    def test_chat_clause_query_scopes_to_dominant_clause_family(self) -> None:
        repo = InMemoryQdrantRepo()
        repo.upsert(
            point_id="ck_431_text",
            vector=[0.1, 0.2],
            payload={
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
            point_id="ck_431_exp",
            vector=[0.2, 0.1],
            payload={
                "doc_name": "spec.pdf",
                "page_start": 47,
                "page_end": 47,
                "excerpt": "4.3.1 条文说明：绝缘油管理工作的好坏，是保证设备质量的关键。",
                "chunk_text": "4.3.1 条文说明：绝缘油管理工作的好坏，是保证设备质量的关键。",
                "source_type": "explanation",
                "route": "explanation_sibling",
                "clause_id": "4.3.1",
            },
        )
        repo.upsert(
            point_id="ck_441_exp",
            vector=[0.3, 0.1],
            payload={
                "doc_name": "spec.pdf",
                "page_start": 50,
                "page_end": 50,
                "excerpt": "4.4.1 条文说明：排氮前应重新浸油。",
                "chunk_text": "4.4.1 条文说明：排氮前应重新浸油。",
                "source_type": "explanation",
                "route": "explanation_sibling",
                "clause_id": "4.4.1",
            },
        )

        res = chat_with_citations(
            question="绝缘油的验收和保管应该服从什么规定",
            repo=repo,
            entity_index=DummyEntityIndex(),
        )

        self.assertIn("条文说明：", res["answer"])
        self.assertIn("4.3.1", res["answer"])
        self.assertNotIn("4.4.1", res["answer"])

    def test_chat_clause_query_ignores_clause_ids_from_feedback_noise(self) -> None:
        repo = InMemoryQdrantRepo()
        repo.upsert(
            point_id="ck_431_text_noise",
            vector=[0.1, 0.2],
            payload={
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
            point_id="ck_431_exp_noise",
            vector=[0.2, 0.1],
            payload={
                "doc_name": "spec.pdf",
                "page_start": 47,
                "page_end": 47,
                "excerpt": "4.3.1 条文说明：绝缘油管理工作的好坏，是保证设备质量的关键。",
                "chunk_text": "4.3.1 条文说明：绝缘油管理工作的好坏，是保证设备质量的关键。",
                "source_type": "explanation",
                "route": "explanation_sibling",
                "clause_id": "4.3.1",
            },
        )
        repo.upsert(
            point_id="ck_441_text_noise",
            vector=[0.3, 0.1],
            payload={
                "doc_name": "spec.pdf",
                "page_start": 20,
                "page_end": 20,
                "excerpt": "4.4.1 采用注油排氮时，应符合下列规定。",
                "chunk_text": "4.4.1 采用注油排氮时，应符合下列规定。",
                "source_type": "text",
                "clause_id": "4.4.1",
            },
        )

        res = chat_with_citations(
            question="绝缘油的验收和保管应该服从什么规定，回复4.4.1及条文说明，但4.3.1却没有查询到",
            repo=repo,
            entity_index=DummyEntityIndex(),
        )

        self.assertIn("4.3.1", res["answer"])
        self.assertNotIn("4.4.1 采用注油排氮", res["answer"])

    def test_chat_clause_query_attaches_clause_siblings_and_prefers_full_chunk_text(self) -> None:
        class _RepoWithClauseSiblings:
            def search(self, query_vector, filter_json=None, limit=5):  # noqa: ARG002
                return [
                    {
                        "id": "clause-main",
                        "score": 9.0,
                        "payload": {
                            "doc_id": "doc_spec",
                            "doc_name": "spec.pdf",
                            "page_start": 19,
                            "page_end": 19,
                            "excerpt": "4.3.1 绝缘油的验收与保管应符合下列规定：1绝缘油应储藏在密封清洁的专用容器内。",
                            "chunk_text": "4.3.1 绝缘油的验收与保管应符合下列规定：1绝缘油应储藏在密封清洁的专用容器内。",
                            "source_type": "text",
                            "clause_id": "4.3.1",
                        },
                    }
                ]

            def keyword_search(self, query_text, filter_json=None, limit=20):  # noqa: ARG002
                return []

            def fetch_by_filter(self, filter_json=None, limit=20):  # noqa: ARG002
                must = (filter_json or {}).get("must") or []
                clause = next((item for item in must if item.get("key") == "clause_id"), {})
                if (clause.get("match") or {}).get("value") != "4.3.1":
                    return []
                return [
                    {
                        "id": "clause-sibling-text",
                        "score": 7.0,
                        "payload": {
                            "doc_id": "doc_spec",
                            "doc_name": "spec.pdf",
                            "page_start": 19,
                            "page_end": 19,
                            "excerpt": "2)取样试验应按现行国家标准执行……",
                            "chunk_text": "2)取样试验应按现行国家标准《电力用油(变压器油、汽轮机油)取样方法》GB7597执行。"
                            "3不同牌号的绝缘油应分别储存，并应有明显牌号标志。"
                            "4放油时应目测，各桶商标应一致。"
                            "5到达现场的绝缘油首次抽取，宜使用压力式滤油机进行粗过滤。",
                            "source_type": "text",
                            "clause_id": "4.3.1",
                        },
                    },
                    {
                        "id": "clause-sibling-explanation",
                        "score": 6.5,
                        "payload": {
                            "doc_id": "doc_spec",
                            "doc_name": "spec.pdf",
                            "page_start": 47,
                            "page_end": 47,
                            "excerpt": "绝缘油管理工作的好坏，是保证设备质量的关键。",
                            "chunk_text": "绝缘油管理工作的好坏，是保证设备质量的关键。"
                            "2绝缘油取样的数量，是根据国家现行标准《电力用油(变压器油、汽轮机油)取样》GB7597作出的规定。",
                            "source_type": "explanation",
                            "clause_id": "4.3.1",
                            "route": "explanation_sibling",
                        },
                    },
                ][: max(1, int(limit))]

            def delete_by_version(self, version_id: str):  # noqa: ARG002
                return None

        old = dict(os.environ)
        os.environ["ENABLE_RERANK"] = "0"
        os.environ["HYBRID_POST_KEYWORD_BOOST"] = "0"
        os.environ["CHAT_CLAUSE_TEMPLATE_ATTACH_SIBLINGS"] = "1"
        try:
            res = chat_with_citations(
                question="绝缘油的验收和保管应该服从什么规定",
                repo=_RepoWithClauseSiblings(),
                entity_index=DummyEntityIndex(),
            )
            self.assertIn("条文规定：", res["answer"])
            self.assertIn("3不同牌号的绝缘油应分别储存", res["answer"])
            self.assertIn("2绝缘油取样的数量", res["answer"])
            self.assertEqual(res["llm"]["model"], "clause-template-v1")
        finally:
            os.environ.clear()
            os.environ.update(old)


if __name__ == "__main__":
    unittest.main()
