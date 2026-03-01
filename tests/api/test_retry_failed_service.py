import json
import tempfile
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.services.doc_registry import JSONDocRegistry  # noqa: E402
from app.services.retry_service import cleanup_failed_versions, reprocess_version, retry_failed_versions  # noqa: E402


class DummyQueue:
    def __init__(self) -> None:
        self.jobs = []

    def enqueue_document_process(self, payload):
        self.jobs.append(payload)


class TestRetryFailedService(unittest.TestCase):
    def _prepare_registry(self, path: Path) -> JSONDocRegistry:
        registry = JSONDocRegistry(path)
        payload = {
            "documents": [
                {"id": "doc_1", "name": "a.pdf"},
                {"id": "doc_2", "name": "b.pdf"},
            ],
            "versions": [
                {
                    "id": "ver_1",
                    "doc_id": "doc_1",
                    "version_no": 1,
                    "storage_key": "pdf/doc_1/ver_1/a.pdf",
                    "status": "failed",
                },
                {
                    "id": "ver_2",
                    "doc_id": "doc_2",
                    "version_no": 1,
                    "storage_key": "pdf/doc_2/ver_2/b.pdf",
                    "status": "processed",
                },
            ],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return registry

    def test_retry_failed_versions_enqueue_and_mark_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            registry = self._prepare_registry(path)
            queue = DummyQueue()

            out = retry_failed_versions(registry=registry, task_queue=queue)

            self.assertEqual(out["retried_count"], 1)
            self.assertEqual(len(queue.jobs), 1)
            self.assertEqual(queue.jobs[0]["version_id"], "ver_1")

            data = json.loads(path.read_text(encoding="utf-8"))
            v1 = next(x for x in data["versions"] if x["id"] == "ver_1")
            self.assertEqual(v1["status"], "retry_queued")

    def test_cleanup_failed_versions_archives_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            registry = self._prepare_registry(path)

            out = cleanup_failed_versions(registry=registry)

            self.assertEqual(out["cleaned_count"], 1)
            data = json.loads(path.read_text(encoding="utf-8"))
            v1 = next(x for x in data["versions"] if x["id"] == "ver_1")
            self.assertEqual(v1["status"], "failed_archived")

    def test_reprocess_version_requeues_processed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            registry = self._prepare_registry(path)
            queue = DummyQueue()

            out = reprocess_version(
                registry=registry,
                task_queue=queue,
                version_id="ver_2",
                runtime_config={"mineru_api_base": "https://mineru.net/api/v4/extract/task", "mineru_api_key": "token"},
            )

            self.assertTrue(out["requeued"])
            self.assertEqual(out["version_id"], "ver_2")
            self.assertEqual(len(queue.jobs), 1)
            self.assertEqual(queue.jobs[0]["version_id"], "ver_2")
            self.assertIn("runtime_config", queue.jobs[0])

            data = json.loads(path.read_text(encoding="utf-8"))
            v2 = next(x for x in data["versions"] if x["id"] == "ver_2")
            self.assertEqual(v2["status"], "retry_queued")

    def test_reprocess_version_returns_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            registry = self._prepare_registry(path)
            queue = DummyQueue()

            out = reprocess_version(registry=registry, task_queue=queue, version_id="ver_x")

            self.assertFalse(out["requeued"])
            self.assertEqual(out["reason"], "not_found")
            self.assertEqual(len(queue.jobs), 0)


if __name__ == "__main__":
    unittest.main()
