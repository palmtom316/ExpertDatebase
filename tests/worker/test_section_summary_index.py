import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.pipeline import process_mineru_result


def test_pipeline_generates_section_summary_chunks() -> None:
    mineru_result = {
        "pages": [
            {
                "page_no": 1,
                "blocks": [
                    {"type": "title", "text": "第4章 绝缘油处理"},
                    {"type": "paragraph", "text": "4.3.1 绝缘油处理前应完成检验。"},
                    {"type": "paragraph", "text": "4.3.2 绝缘油处理后应进行复核。"},
                ],
                "tables": [],
            }
        ]
    }

    out = process_mineru_result(doc_id="doc_sum", version_id="ver_sum", mineru_result=mineru_result)
    summaries = [c for c in out["chunks"] if str(c.get("source_type") or "") == "section_summary"]

    assert summaries
    assert any("绝缘油处理" in str(c.get("text") or "") for c in summaries)
