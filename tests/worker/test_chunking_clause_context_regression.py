import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.chunking import chunk_chapters


def test_chunking_keeps_clause_context_when_line_contains_external_clause_reference() -> None:
    chapters = [
        {
            "chapter_id": "ch_43",
            "start_page": 47,
            "end_page": 47,
            "blocks": [
                {
                    "block_id": "b_47_1",
                    "page_no": 47,
                    "text": "4.3.1 绝缘油管理工作的好坏，是保证设备质量的关键，应引起充分注意。",
                },
                {
                    "block_id": "b_47_2",
                    "page_no": 47,
                    "text": "2 绝缘油取样的数量，是根据GB7597中第2.1.1.4款规定取样。",
                },
            ],
            "text": "unused",
        }
    ]
    chunks = chunk_chapters(
        doc_id="doc_1",
        version_id="ver_1",
        chapters=chapters,
        min_chars=1,
        max_chars=500,
        overlap_chars=0,
    )
    assert chunks
    assert any("第2.1.1.4款" in str(c.get("text") or "") for c in chunks)
    assert all(str(c.get("clause_id") or "") == "4.3.1" for c in chunks)
    assert all(str(c.get("clause_id") or "") != "2.1.1.4" for c in chunks)
