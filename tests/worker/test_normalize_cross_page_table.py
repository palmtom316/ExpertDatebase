import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.normalize import normalize_result


def test_normalize_merges_cross_page_table() -> None:
    mineru_result = {
        "pages": [
            {
                "page_no": 4,
                "blocks": [],
                "tables": [{"raw_text": "序号|设备电压等级(V)|兆欧表电压等级(V)\n1|<100|250"}],
            },
            {
                "page_no": 5,
                "blocks": [],
                "tables": [{"raw_text": "续表3.0.9\n序号|设备电压等级(V)|兆欧表电压等级(V)\n2|<500|500"}],
            },
        ]
    }
    _, tables = normalize_result(mineru_result)
    assert len(tables) == 1
    merged = tables[0]
    assert merged["page_start"] == 4
    assert merged["page_end"] == 5
    assert "1|<100|250" in merged["raw_text"]
    assert "2|<500|500" in merged["raw_text"]
