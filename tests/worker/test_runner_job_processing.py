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
