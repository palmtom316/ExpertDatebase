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


if __name__ == "__main__":
    unittest.main()
