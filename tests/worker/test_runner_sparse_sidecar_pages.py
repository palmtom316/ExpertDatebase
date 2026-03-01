import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.embedding_client import EmbeddingClient
from worker.runner import WorkerRuntime, process_document_job


class FakeStorage:
    def get_bytes(self, object_key: str) -> bytes:  # noqa: ARG002
        return b"%PDF-1.4 mock%%EOF"


class FakeMinerU:
    def parse_pdf(self, pdf_bytes: bytes):  # noqa: ARG002
        return {
            "pages": [
                {
                    "page_no": 1,
                    "blocks": [{"type": "paragraph", "text": "第一页 电容器说明"}],
                    "tables": [],
                },
                {
                    "page_no": 2,
                    "blocks": [{"type": "paragraph", "text": "第二页 11.4.1 条款内容"}],
                    "tables": [],
                },
            ]
        }


class FakeRegistry:
    def __init__(self) -> None:
        self.calls = []

    def mark_version_status(self, version_id: str, status: str, notes=None):
        self.calls.append((version_id, status, notes))


class FakeQdrant:
    def upsert(self, point_id, vector, payload):  # noqa: ARG002
        return None


def test_runner_exports_page_sidecar_texts(tmp_path: Path) -> None:
    os.environ["SPARSE_SIDECAR_DOCS_ROOT"] = str(tmp_path)
    rt = WorkerRuntime(
        storage=FakeStorage(),
        qdrant_repo=FakeQdrant(),
        doc_registry=FakeRegistry(),
        mineru_client=FakeMinerU(),
        embedding_client=EmbeddingClient(),
    )
    job = {"doc_id": "doc_7", "version_id": "ver_7", "object_key": "pdf/doc_7/ver_7/sample.pdf"}
    process_document_job(job, rt)

    page1 = tmp_path / "doc_7" / "page_001.txt"
    page2 = tmp_path / "doc_7" / "page_002.txt"
    assert page1.exists()
    assert page2.exists()
    assert "第一页 电容器说明" in page1.read_text(encoding="utf-8")
    assert "11.4.1" in page2.read_text(encoding="utf-8")
