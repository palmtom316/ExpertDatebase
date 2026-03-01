import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.chapters import build_chapters


def test_chapters_detect_numeric_space_titles() -> None:
    blocks = [
        {"block_id": "b1", "page_no": 1, "block_type": "title", "text": "1 总则", "order_in_page": 1},
        {"block_id": "b2", "page_no": 1, "block_type": "paragraph", "text": "内容 A", "order_in_page": 2},
        {"block_id": "b3", "page_no": 2, "block_type": "title", "text": "2 基本规定", "order_in_page": 1},
        {"block_id": "b4", "page_no": 2, "block_type": "paragraph", "text": "内容 B", "order_in_page": 2},
    ]
    chapters = build_chapters(blocks, min_merge_chars=0)
    assert len(chapters) >= 2
    assert chapters[0]["title"].startswith("1 ")
    assert chapters[1]["title"].startswith("2 ")


def test_chapters_avoid_long_clause_sentence_as_title() -> None:
    blocks = [
        {"block_id": "b1", "page_no": 1, "block_type": "title", "text": "3 基本规定", "order_in_page": 1},
        {
            "block_id": "b2",
            "page_no": 1,
            "block_type": "paragraph",
            "text": "3.0.12 高压电器设备的交接试验应按照现行国家标准执行。",
            "order_in_page": 2,
        },
        {"block_id": "b3", "page_no": 2, "block_type": "title", "text": "4 六氟化硫断路器", "order_in_page": 1},
    ]
    chapters = build_chapters(blocks, min_merge_chars=0)
    assert len(chapters) == 2
    assert chapters[0]["title"].startswith("3 ")
    assert chapters[1]["title"].startswith("4 ")
