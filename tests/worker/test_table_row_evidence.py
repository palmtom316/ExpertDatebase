import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.pipeline import process_mineru_result


def test_pipeline_generates_table_row_chunks_for_evidence() -> None:
    mineru_result = {
        "pages": [
            {
                "page_no": 9,
                "blocks": [{"type": "title", "text": "设备参数"}],
                "tables": [
                    {
                        "raw_text": "设备|型号|数量\n断路器|ZW32|12\n电容器|TBB|3",
                    }
                ],
            }
        ]
    }

    out = process_mineru_result(doc_id="doc_a", version_id="ver_a", mineru_result=mineru_result)
    chunks = out["chunks"]
    table_chunks = [c for c in chunks if str(c.get("chunk_id", "")).startswith("tbl_")]
    assert table_chunks
    assert any("断路器" in str(c.get("text") or "") for c in table_chunks)
