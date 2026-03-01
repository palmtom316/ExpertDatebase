import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.embedding_client import EmbeddingClient
from worker.runner import WorkerRuntime, process_document_job


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def get_bytes(self, object_key: str) -> bytes:
        return b"%PDF-1.4 mock%%EOF"

    def put_bytes(self, object_key: str, content: bytes, content_type: str | None = None) -> None:
        self.objects[object_key] = content


class FakeMinerU:
    def parse_pdf(self, pdf_bytes: bytes):  # noqa: ARG002
        return {
            "pages": [
                {
                    "page_no": 1,
                    "blocks": [
                        {"type": "title", "text": "第11章 电容器"},
                        {"type": "paragraph", "text": "11.1 电容器安装应满足设计要求。"},
                    ],
                    "tables": [{"raw_text": "设备|参数"}],
                }
            ]
        }


class FakeRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []

    def mark_version_status(self, version_id: str, status: str, notes=None):
        self.calls.append((version_id, status, notes))


class FakeQdrant:
    def upsert(self, point_id, vector, payload):  # noqa: ARG002
        return None


def test_runner_exports_mineru_artifacts_to_storage() -> None:
    storage = FakeStorage()
    registry = FakeRegistry()
    rt = WorkerRuntime(
        storage=storage,
        qdrant_repo=FakeQdrant(),
        doc_registry=registry,
        mineru_client=FakeMinerU(),
        embedding_client=EmbeddingClient(),
    )
    job = {"doc_id": "doc_1", "version_id": "ver_1", "object_key": "pdf/doc_1/ver_1/sample.pdf"}
    process_document_job(job, rt)

    json_key = "mineru/doc_1/ver_1/mineru.pages.json"
    md_key = "mineru/doc_1/ver_1/mineru.pages.md"
    assert json_key in storage.objects
    assert md_key in storage.objects

    exported = json.loads(storage.objects[json_key].decode("utf-8"))
    assert (exported.get("pages") or [])[0]["blocks"][0]["text"] == "第11章 电容器"
    notes = registry.calls[-1][2] or {}
    assert ((notes.get("artifacts") or {}).get("mineru_json_key")) == json_key
    assert ((notes.get("artifacts") or {}).get("mineru_md_key")) == md_key

