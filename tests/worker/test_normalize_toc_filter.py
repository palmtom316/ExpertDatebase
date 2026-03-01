import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.normalize import normalize_result


def test_normalize_filters_toc_like_blocks() -> None:
    mineru_result = {
        "pages": [
            {
                "page_no": 1,
                "blocks": [
                    {"type": "paragraph", "text": "11.1General requirement …(50) 11.2Installation ...(52)"},
                    {"type": "paragraph", "text": "3 基本规定 (5)"},
                    {"type": "paragraph", "text": "5.3GIS中的六氟化硫断路器的安装 (20）"},
                    {"type": "title", "text": "6 真空断路器和高压开关柜"},
                    {"type": "paragraph", "text": "6.1.2 真空断路器和高压开关柜运到现场后，包装应完好。"},
                ],
                "tables": [],
            }
        ]
    }

    blocks, tables = normalize_result(mineru_result)
    assert len(tables) == 0
    texts = [b["text"] for b in blocks]
    assert all("11.1General requirement" not in t for t in texts)
    assert all("3 基本规定 (5)" not in t for t in texts)
    assert all("5.3GIS中的六氟化硫断路器的安装" not in t for t in texts)
    assert any("真空断路器和高压开关柜" in t for t in texts)
