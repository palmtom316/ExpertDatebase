import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.services.retrieval.structured_lookup import StructuredLookupService


def test_structured_lookup_hits_certificate_and_standard(tmp_path: Path) -> None:
    assets_path = tmp_path / "assets.jsonl"
    rows = [
        {
            "id": "a1",
            "doc_id": "doc_cert",
            "version_id": "ver_1",
            "asset_type": "qualification",
            "data_json": {"certificate": "ZJ-A-2024-009", "person_name": "王磊"},
            "source_page": 7,
            "source_excerpt": "资格证书 ZJ-A-2024-009",
            "source_type": "chapter_text",
        },
        {
            "id": "a2",
            "doc_id": "doc_std",
            "version_id": "ver_1",
            "asset_type": "standard",
            "data_json": {"standard_name": "GB 50147-2010"},
            "source_page": 12,
            "source_excerpt": "执行标准 GB 50147-2010",
            "source_type": "chapter_text",
        },
    ]
    assets_path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in rows) + "\n", encoding="utf-8")

    os.environ["ASSET_JSONL_PATH"] = str(assets_path)
    service = StructuredLookupService()

    hits = service.lookup("证书号ZJ-A-2024-009和标准GB 50147-2010分别在哪一页？", top_n=5)

    assert len(hits) == 2
    doc_ids = {hit["doc_id"] for hit in hits}
    assert "doc_cert" in doc_ids
    assert "doc_std" in doc_ids
