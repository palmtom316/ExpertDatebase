import os
import tempfile
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.api.upload import upload_pdf_bytes  # noqa: E402
from app.services.doc_registry import JSONDocRegistry  # noqa: E402
from app.services.storage import MinioObjectStorage, build_storage_from_env  # noqa: E402
from app.services.task_queue import RedisTaskQueue, build_task_queue_from_env  # noqa: E402


class DummyQueue:
    def __init__(self) -> None:
        self.jobs = []

    def enqueue_document_process(self, payload):
        self.jobs.append(payload)


class TestUploadQueueAndFactories(unittest.TestCase):
    def test_upload_enqueues_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from app.services.storage import LocalObjectStorage

            storage = LocalObjectStorage(Path(tmp) / "objects")
            registry = JSONDocRegistry(Path(tmp) / "registry.json")
            queue = DummyQueue()

            result = upload_pdf_bytes(
                filename="sample.pdf",
                content=b"%PDF-1.4 mock",
                storage=storage,
                registry=registry,
                task_queue=queue,
            )

            self.assertEqual(len(queue.jobs), 1)
            self.assertEqual(queue.jobs[0]["doc_id"], result["doc_id"])
            self.assertEqual(queue.jobs[0]["version_id"], result["version_id"])

    def test_storage_factory_builds_minio(self) -> None:
        old = dict(os.environ)
        try:
            os.environ["MINIO_ENDPOINT"] = "http://minio:9000"
            os.environ["MINIO_ACCESS_KEY"] = "minio"
            os.environ["MINIO_SECRET_KEY"] = "minio123"
            os.environ["MINIO_BUCKET"] = "expertkb"
            s = build_storage_from_env()
            self.assertIsInstance(s, MinioObjectStorage)
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_queue_factory_builds_redis(self) -> None:
        old = dict(os.environ)
        try:
            os.environ["REDIS_URL"] = "redis://localhost:6379/0"
            q = build_task_queue_from_env()
            self.assertIsInstance(q, RedisTaskQueue)
        finally:
            os.environ.clear()
            os.environ.update(old)


if __name__ == "__main__":
    unittest.main()
