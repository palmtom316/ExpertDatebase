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
                doc_type="公司资质",
                runtime_config={
                    "ocr_provider": "siliconflow",
                    "ocr_api_key": "ocr-key",
                    "ocr_model": "deepseek-ai/DeepSeek-OCR",
                    "ocr_base_url": "https://api.siliconflow.cn/v1",
                    "mineru_api_base": "https://mineru.example.com",
                    "mineru_api_key": "mineru-key",
                    "llm_provider": "openai",
                    "llm_api_key": "llm-key",
                    "llm_model": "gpt-4o-mini",
                    "embedding_provider": "openai",
                    "embedding_api_key": "emb-key",
                    "embedding_model": "text-embedding-3-small",
                    "embedding_dimensions": "1024",
                    "rerank_provider": "local",
                    "rerank_model": "gpt-4o-mini",
                    "vl_provider": "openai",
                    "vl_api_key": "vl-key",
                    "vl_model": "gpt-4o-mini",
                    "vl_base_url": "https://api.openai.com/v1",
                },
            )

            self.assertEqual(len(queue.jobs), 1)
            self.assertEqual(queue.jobs[0]["doc_id"], result["doc_id"])
            self.assertEqual(queue.jobs[0]["version_id"], result["version_id"])
            self.assertEqual(queue.jobs[0]["runtime_config"]["mineru_api_base"], "https://mineru.example.com")
            self.assertEqual(queue.jobs[0]["runtime_config"]["ocr_provider"], "siliconflow")
            self.assertEqual(queue.jobs[0]["runtime_config"]["llm_provider"], "openai")
            self.assertEqual(queue.jobs[0]["runtime_config"]["embedding_provider"], "openai")
            self.assertEqual(queue.jobs[0]["runtime_config"]["embedding_dimensions"], "1024")
            self.assertEqual(queue.jobs[0]["runtime_config"]["rerank_provider"], "local")
            self.assertEqual(queue.jobs[0]["runtime_config"]["vl_provider"], "openai")
            self.assertEqual(queue.jobs[0]["doc_type"], "公司资质")
            self.assertEqual(result.get("doc_type"), "公司资质")
            self.assertIn("/company-qualification/", result["object_key"])

    def test_upload_deduplicates_by_content_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from app.services.storage import LocalObjectStorage

            storage = LocalObjectStorage(Path(tmp) / "objects")
            registry = JSONDocRegistry(Path(tmp) / "registry.json")
            queue = DummyQueue()
            data = b"%PDF-1.4 same-content"

            first = upload_pdf_bytes(
                filename="same.pdf",
                content=data,
                storage=storage,
                registry=registry,
                task_queue=queue,
            )
            second = upload_pdf_bytes(
                filename="same.pdf",
                content=data,
                storage=storage,
                registry=registry,
                task_queue=queue,
            )

            self.assertFalse(first.get("deduplicated"))
            self.assertTrue(second.get("deduplicated"))
            self.assertEqual(first["doc_id"], second["doc_id"])
            self.assertEqual(first["version_id"], second["version_id"])
            self.assertEqual(first["object_key"], second["object_key"])
            self.assertEqual(len(queue.jobs), 1)

    def test_upload_dedup_skips_failed_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from app.services.storage import LocalObjectStorage

            storage = LocalObjectStorage(Path(tmp) / "objects")
            registry = JSONDocRegistry(Path(tmp) / "registry.json")
            queue = DummyQueue()
            data = b"%PDF-1.4 failed-content"

            first = upload_pdf_bytes(
                filename="failed.pdf",
                content=data,
                storage=storage,
                registry=registry,
                task_queue=queue,
            )
            registry.update_version_status(first["version_id"], "failed", notes={"error": "mock"})

            second = upload_pdf_bytes(
                filename="failed.pdf",
                content=data,
                storage=storage,
                registry=registry,
                task_queue=queue,
            )

            self.assertNotEqual(first["version_id"], second["version_id"])
            self.assertFalse(second.get("deduplicated"))
            self.assertEqual(len(queue.jobs), 2)

    def test_upload_dedup_requeues_processed_when_runtime_mineru_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from app.services.storage import LocalObjectStorage

            storage = LocalObjectStorage(Path(tmp) / "objects")
            registry = JSONDocRegistry(Path(tmp) / "registry.json")
            queue = DummyQueue()
            data = b"%PDF-1.4 reprocess-content"

            first = upload_pdf_bytes(
                filename="reprocess.pdf",
                content=data,
                storage=storage,
                registry=registry,
                task_queue=queue,
            )
            self.assertEqual(len(queue.jobs), 1)
            registry.update_version_status(first["version_id"], "processed", notes={"ok": True})

            second = upload_pdf_bytes(
                filename="reprocess.pdf",
                content=data,
                storage=storage,
                registry=registry,
                task_queue=queue,
                runtime_config={
                    "mineru_api_base": "https://mineru.net/api/v4/extract/task",
                    "mineru_api_key": "token",
                },
            )

            self.assertTrue(second.get("deduplicated"))
            self.assertTrue(second.get("requeued"))
            self.assertEqual(second.get("status"), "retry_queued")
            self.assertEqual(first["version_id"], second["version_id"])
            self.assertEqual(len(queue.jobs), 2)
            self.assertEqual(queue.jobs[-1]["version_id"], first["version_id"])
            self.assertIn("doc_type", queue.jobs[-1])

    def test_upload_dedup_requeues_processed_when_runtime_ocr_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from app.services.storage import LocalObjectStorage

            storage = LocalObjectStorage(Path(tmp) / "objects")
            registry = JSONDocRegistry(Path(tmp) / "registry.json")
            queue = DummyQueue()
            data = b"%PDF-1.4 reprocess-ocr-content"

            first = upload_pdf_bytes(
                filename="reprocess-ocr.pdf",
                content=data,
                storage=storage,
                registry=registry,
                task_queue=queue,
            )
            registry.update_version_status(first["version_id"], "processed", notes={"ok": True})

            second = upload_pdf_bytes(
                filename="reprocess-ocr.pdf",
                content=data,
                storage=storage,
                registry=registry,
                task_queue=queue,
                runtime_config={
                    "ocr_provider": "siliconflow",
                    "ocr_api_key": "ocr-key",
                    "ocr_base_url": "https://api.siliconflow.cn/v1",
                    "ocr_model": "deepseek-ai/DeepSeek-OCR",
                },
            )

            self.assertTrue(second.get("deduplicated"))
            self.assertTrue(second.get("requeued"))
            self.assertEqual(second.get("status"), "retry_queued")
            self.assertEqual(first["version_id"], second["version_id"])
            self.assertEqual(len(queue.jobs), 2)
            self.assertEqual(queue.jobs[-1]["runtime_config"]["ocr_provider"], "siliconflow")

    def test_registry_can_filter_versions_by_doc_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from app.services.storage import LocalObjectStorage

            storage = LocalObjectStorage(Path(tmp) / "objects")
            registry = JSONDocRegistry(Path(tmp) / "registry.json")

            upload_pdf_bytes(
                filename="a.pdf",
                content=b"%PDF-1.4 a",
                storage=storage,
                registry=registry,
                doc_type="规范规程",
            )
            upload_pdf_bytes(
                filename="b.pdf",
                content=b"%PDF-1.4 b",
                storage=storage,
                registry=registry,
                doc_type="人员资质",
            )

            rows = registry.list_versions(doc_type="人员资质")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].get("doc_type"), "人员资质")

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
            os.environ.pop("TASK_QUEUE_BACKEND", None)  # let factory auto-detect
            q = build_task_queue_from_env()
            self.assertIsInstance(q, RedisTaskQueue)
        finally:
            os.environ.clear()
            os.environ.update(old)


if __name__ == "__main__":
    unittest.main()
