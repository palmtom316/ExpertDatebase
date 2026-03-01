import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.chunking import chunk_chapters


def test_chunking_uses_block_level_page_range() -> None:
    chapters = [
        {
            "chapter_id": "ch_1",
            "start_page": 1,
            "end_page": 12,
            "blocks": [
                {"block_id": "b_1_1", "page_no": 1, "text": "第一章 总则。"},
                {"block_id": "b_11_1", "page_no": 11, "text": "11.1 电容器安装应满足设计要求。"},
                {"block_id": "b_12_1", "page_no": 12, "text": "11.4.1 串联电容补偿装置应符合规定。"},
            ],
            "text": "unused",
        }
    ]
    chunks = chunk_chapters(
        doc_id="doc_1",
        version_id="ver_1",
        chapters=chapters,
        min_chars=1,
        max_chars=25,
        overlap_chars=0,
    )
    assert len(chunks) >= 2
    cap_chunk = next(c for c in chunks if "电容器" in c["text"])
    clause_chunk = next(c for c in chunks if "11.4.1" in c["text"])
    assert cap_chunk["page_start"] == 11
    assert cap_chunk["page_end"] == 11
    assert clause_chunk["page_start"] == 12
    assert clause_chunk["page_end"] == 12


def test_chunking_preserves_clause_identifier() -> None:
    chapters = [
        {
            "chapter_id": "ch_1",
            "start_page": 5,
            "end_page": 5,
            "blocks": [
                {
                    "block_id": "b_5_1",
                    "page_no": 5,
                    "text": "11.4.1 串联电容补偿装置在运输和装卸过程中不得倾倒。",
                }
            ],
            "text": "unused",
        }
    ]
    chunks = chunk_chapters(
        doc_id="doc_1",
        version_id="ver_1",
        chapters=chapters,
        min_chars=1,
        max_chars=120,
        overlap_chars=0,
    )
    assert len(chunks) == 1
    assert "11.4.1" in chunks[0]["text"]
