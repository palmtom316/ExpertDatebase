import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.services.search_service import QdrantHttpRepo  # noqa: E402


class TestQdrantHttpRepo(unittest.TestCase):
    @patch("app.services.search_service.requests.post")
    def test_search_posts_expected_payload(self, m_post: Mock) -> None:
        resp = Mock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "result": [
                {"id": "ck1", "score": 0.9, "payload": {"doc_name": "demo.pdf", "excerpt": "证据"}}
            ]
        }
        m_post.return_value = resp

        repo = QdrantHttpRepo(endpoint="http://localhost:6333", collection="chunks_v1", vector_name="text_embedding")
        out = repo.search(query_vector=[0.1, 0.2], filter_json={"must": []}, limit=3)

        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], "ck1")

        _, kwargs = m_post.call_args
        self.assertIn("json", kwargs)
        body = kwargs["json"]
        self.assertEqual(body["limit"], 3)
        self.assertIn("filter", body)


if __name__ == "__main__":
    unittest.main()
