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

    @patch("app.services.search_service.requests.post")
    def test_search_returns_empty_when_collection_missing(self, m_post: Mock) -> None:
        from requests import HTTPError

        resp = Mock()
        resp.status_code = 404
        resp.raise_for_status.side_effect = HTTPError("404 Client Error", response=resp)
        m_post.return_value = resp

        repo = QdrantHttpRepo(endpoint="http://localhost:6333", collection="chunks_v1", vector_name="text_embedding")
        out = repo.search(query_vector=[0.1, 0.2], filter_json=None, limit=3)

        self.assertEqual(out, [])

    @patch("app.services.search_service.requests.post")
    def test_search_returns_empty_when_vector_dimension_mismatch(self, m_post: Mock) -> None:
        from requests import HTTPError

        resp = Mock()
        resp.status_code = 400
        resp.text = "Wrong input: Vector dimension error: expected dim: 1024, got 1536"
        resp.raise_for_status.side_effect = HTTPError("400 Client Error", response=resp)
        m_post.return_value = resp

        repo = QdrantHttpRepo(endpoint="http://localhost:6333", collection="chunks_v1", vector_name="text_embedding")
        out = repo.search(query_vector=[0.1, 0.2], filter_json=None, limit=3)

        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()
