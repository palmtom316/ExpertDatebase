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


class FakeMinerUWithNul:
    def parse_pdf(self, pdf_bytes: bytes):  # noqa: ARG002
        return {
            "pages": [
                {
                    "page_no": 1,
                    "blocks": [{"type": "paragraph", "text": "第一\x00页 4.3.1 条文"}],
                    "tables": [{"raw_text": "列A\x00 列B"}],
                }
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


class FakeDocPagesRepo:
    def __init__(self) -> None:
        self.calls = []

    def upsert_pages(self, doc_id: str, version_id: str, pages):
        self.calls.append((doc_id, version_id, list(pages)))
        return len(list(pages))


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


def test_runner_upserts_doc_pages_for_sparse_retrieval(tmp_path: Path) -> None:
    os.environ["SPARSE_SIDECAR_DOCS_ROOT"] = str(tmp_path)
    doc_pages_repo = FakeDocPagesRepo()
    rt = WorkerRuntime(
        storage=FakeStorage(),
        qdrant_repo=FakeQdrant(),
        doc_registry=FakeRegistry(),
        mineru_client=FakeMinerU(),
        embedding_client=EmbeddingClient(),
        doc_pages_repo=doc_pages_repo,
    )
    job = {"doc_id": "doc_8", "version_id": "ver_8", "object_key": "pdf/doc_8/ver_8/sample.pdf"}
    summary = process_document_job(job, rt)

    assert summary.get("doc_pages_upserted") == 2
    assert len(doc_pages_repo.calls) == 1
    _, _, rows = doc_pages_repo.calls[0]
    assert len(rows) == 2
    assert rows[0]["page_no"] == 1
    assert "第一页 电容器说明" in rows[0]["text"]


def test_runner_strips_nul_from_doc_pages_and_sidecar(tmp_path: Path) -> None:
    os.environ["SPARSE_SIDECAR_DOCS_ROOT"] = str(tmp_path)
    doc_pages_repo = FakeDocPagesRepo()
    rt = WorkerRuntime(
        storage=FakeStorage(),
        qdrant_repo=FakeQdrant(),
        doc_registry=FakeRegistry(),
        mineru_client=FakeMinerUWithNul(),
        embedding_client=EmbeddingClient(),
        doc_pages_repo=doc_pages_repo,
    )
    job = {"doc_id": "doc_9", "version_id": "ver_9", "object_key": "pdf/doc_9/ver_9/sample.pdf"}
    process_document_job(job, rt)

    _, _, rows = doc_pages_repo.calls[0]
    assert "\x00" not in rows[0]["text"]
    page1 = tmp_path / "doc_9" / "page_001.txt"
    assert page1.exists()
    assert "\x00" not in page1.read_text(encoding="utf-8")
