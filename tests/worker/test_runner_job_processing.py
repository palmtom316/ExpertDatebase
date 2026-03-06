import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.embedding_client import EmbeddingClient
from worker.runner import WorkerRuntime, process_document_job


class FakeStorage:
    def get_bytes(self, object_key: str) -> bytes:
        return "张建国项目经理，合同金额5000万元。".encode("utf-8")


class FakeMinerU:
    def parse_pdf(self, pdf_bytes: bytes):
        return {
            "pages": [
                {
                    "page_no": 1,
                    "blocks": [
                        {"type": "title", "text": "第一章 项目"},
                        {"type": "paragraph", "text": pdf_bytes.decode('utf-8')},
                    ],
                    "tables": [],
                }
            ]
        }


class FakeRegistry:
    def __init__(self):
        self.calls = []

    def mark_version_status(self, version_id: str, status: str, notes=None):
        self.calls.append((version_id, status, notes))


class FakeQdrant:
    def __init__(self):
        self.items = []
        self.deleted_versions = []

    def upsert(self, point_id, vector, payload):
        self.items.append({"id": point_id, "vector": vector, "payload": payload})

    def delete_by_version(self, version_id):
        self.deleted_versions.append(version_id)


class FakeBatchEmbeddingClient:
    def __init__(self) -> None:
        self.batch_calls = []

    def embed_texts(self, texts, runtime_config=None):
        self.batch_calls.append({"texts": list(texts), "runtime_config": runtime_config})
        return [[0.1, 0.2, 0.3] for _ in texts]

    def pop_last_call_meta(self):
        item_count = len(self.batch_calls[-1]["texts"]) if self.batch_calls else 0
        return {
            "provider": "siliconflow",
            "model": "Qwen/Qwen3-Embedding-8B",
            "used_stub": False,
            "fallback_reason": "",
            "item_count": item_count,
            "request_count": 1,
        }


def test_process_document_job_updates_status_and_upserts_chunks() -> None:
    rt = WorkerRuntime(
        storage=FakeStorage(),
        qdrant_repo=FakeQdrant(),
        doc_registry=FakeRegistry(),
        mineru_client=FakeMinerU(),
        embedding_client=EmbeddingClient(),
    )
    job = {"doc_id": "doc_1", "version_id": "ver_1", "object_key": "pdf/doc_1/ver_1/sample.pdf"}

    summary = process_document_job(job, rt)

    assert summary["upserted"] >= 1
    assert rt.doc_registry.calls[0][1] == "processing"
    assert rt.doc_registry.calls[-1][1] == "processed"
    assert len(rt.qdrant_repo.items) >= 1
    assert rt.qdrant_repo.deleted_versions == ["ver_1"]
    first = rt.qdrant_repo.items[0]
    assert str(first["id"]).startswith("doc_1:ver_1:")
    assert first["payload"]["version_id"] == "ver_1"
    assert "table_repair_counts" in summary
    assert summary["table_repair_counts"]["none"] >= 0
    assert summary["table_repair_counts"]["stub"] >= 0
    assert summary["table_repair_counts"]["vl_fallback"] >= 0
    assert isinstance(summary.get("table_vl_attempted"), int)
    assert isinstance(summary.get("table_vl_applied"), int)


def test_process_document_job_batches_embeddings_when_supported() -> None:
    embedding_client = FakeBatchEmbeddingClient()
    rt = WorkerRuntime(
        storage=FakeStorage(),
        qdrant_repo=FakeQdrant(),
        doc_registry=FakeRegistry(),
        mineru_client=FakeMinerU(),
        embedding_client=embedding_client,
    )
    job = {"doc_id": "doc_batch", "version_id": "ver_batch", "object_key": "pdf/doc_batch/ver_batch/sample.pdf"}

    summary = process_document_job(job, rt)

    assert len(embedding_client.batch_calls) == 1
    assert len(embedding_client.batch_calls[0]["texts"]) == summary["chunks"]
    assert summary["embedding_stats"]["request_calls"] == 1
    assert summary["embedding_stats"]["chunk_calls"] == summary["chunks"]


def test_process_document_job_redacts_runtime_secrets_in_processing_notes() -> None:
    registry = FakeRegistry()
    rt = WorkerRuntime(
        storage=FakeStorage(),
        qdrant_repo=FakeQdrant(),
        doc_registry=registry,
        mineru_client=FakeMinerU(),
        embedding_client=EmbeddingClient(),
    )
    job = {
        "doc_id": "doc_secret",
        "version_id": "ver_secret",
        "object_key": "pdf/doc_secret/ver_secret/sample.pdf",
        "runtime_config": {
            "embedding_api_key": "emb-secret",
            "ocr_api_key": "ocr-secret",
            "mineru_token": "token-secret",
        },
    }

    process_document_job(job, rt)

    processing_notes = registry.calls[0][2]
    runtime_config = processing_notes["job"]["runtime_config"]
    assert runtime_config["embedding_api_key"] == "***"
    assert runtime_config["ocr_api_key"] == "***"
    assert runtime_config["mineru_token"] == "***"
