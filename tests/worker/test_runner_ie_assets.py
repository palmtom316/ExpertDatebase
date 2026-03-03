import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / 'services' / 'worker'
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.embedding_client import EmbeddingClient
from worker.runner import WorkerRuntime, process_document_job


class FakeStorage:
    def get_bytes(self, object_key: str) -> bytes:
        return '项目名称：城南变电站\n合同金额：5000万元\n业主单位：某电力公司'.encode('utf-8')


class FakeMinerU:
    def parse_pdf(self, pdf_bytes: bytes):
        return {
            'pages': [
                {
                    'page_no': 1,
                    'blocks': [
                        {'type': 'title', 'text': '第一章 项目概况'},
                        {'type': 'paragraph', 'text': pdf_bytes.decode('utf-8')},
                    ],
                    'tables': [],
                }
            ]
        }


class FakeMinerUMultiPage:
    def parse_pdf(self, pdf_bytes: bytes):  # noqa: ARG002
        return {
            "pages": [
                {
                    "page_no": 1,
                    "blocks": [
                        {"type": "paragraph", "text": "项目名称：城南变电站"},
                    ],
                    "tables": [],
                },
                {
                    "page_no": 2,
                    "blocks": [
                        {"type": "paragraph", "text": "标准：GB 50148-2010"},
                    ],
                    "tables": [],
                },
            ]
        }


class FakeRegistry:
    def mark_version_status(self, version_id: str, status: str, notes=None):
        pass


class FakeQdrant:
    def upsert(self, point_id, vector, payload):
        pass


class FakeAssetRepo:
    def __init__(self):
        self.assets = []

    def write_assets(self, doc_id: str, version_id: str, assets):
        self.assets.extend(assets)


def test_runner_extracts_and_persists_assets() -> None:
    asset_repo = FakeAssetRepo()
    rt = WorkerRuntime(
        storage=FakeStorage(),
        qdrant_repo=FakeQdrant(),
        doc_registry=FakeRegistry(),
        mineru_client=FakeMinerU(),
        embedding_client=EmbeddingClient(),
        asset_repo=asset_repo,
    )

    summary = process_document_job({'doc_id': 'doc1', 'version_id': 'ver1', 'object_key': 'pdf/doc1/ver1/a.pdf'}, rt)

    assert summary['assets_written'] >= 1
    assert len(asset_repo.assets) >= 1


def test_runner_ie_assets_follow_real_page_numbers() -> None:
    asset_repo = FakeAssetRepo()
    rt = WorkerRuntime(
        storage=FakeStorage(),
        qdrant_repo=FakeQdrant(),
        doc_registry=FakeRegistry(),
        mineru_client=FakeMinerUMultiPage(),
        embedding_client=EmbeddingClient(),
        asset_repo=asset_repo,
    )

    summary = process_document_job({"doc_id": "doc2", "version_id": "ver2", "object_key": "pdf/doc2/ver2/a.pdf"}, rt)

    assert summary["assets_written"] >= 2
    pages = {int(item.get("source_page") or 0) for item in asset_repo.assets}
    assert 1 in pages
    assert 2 in pages
