import os
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
    assert all(str(c.get("page_type") or "") == "table" for c in table_chunks)


def test_pipeline_table_three_pack_and_explanation_chunks_with_flags() -> None:
    old = dict(os.environ)
    os.environ["WORKER_ENABLE_TABLE_THREE_PACK"] = "1"
    os.environ["WORKER_ENABLE_EXPLANATION_CHUNKS"] = "1"
    try:
        mineru_result = {
            "pages": [
                {
                    "page_no": 6,
                    "blocks": [
                        {"type": "paragraph", "text": "3.2.1 条文说明：设备参数应满足运行要求。"},
                    ],
                    "tables": [
                        {
                            "raw_text": "参数|值\n额定电压|110kV\n容量|31.5MVA",
                        }
                    ],
                }
            ]
        }

        out = process_mineru_result(doc_id="doc_b", version_id="ver_b", mineru_result=mineru_result)
        chunks = out["chunks"]
        source_types = {str(c.get("source_type") or "") for c in chunks}

        assert "table_row" in source_types
        assert "table_raw" in source_types
        assert "table_summary" in source_types
        assert "explanation" in source_types

        table_raw = next(c for c in chunks if str(c.get("source_type") or "") == "table_raw")
        table_summary = next(c for c in chunks if str(c.get("source_type") or "") == "table_summary")
        explanation = next(c for c in chunks if str(c.get("source_type") or "") == "explanation")

        assert str(table_raw.get("table_repr") or "") == "raw"
        assert str(table_summary.get("table_repr") or "") == "summary"
        assert str(explanation.get("doc_type") or "") == "explanation"
        assert str(explanation.get("clause_id") or "") == "3.2.1"
    finally:
        os.environ.clear()
        os.environ.update(old)
