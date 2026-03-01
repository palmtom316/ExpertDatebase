import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.quality_gate import filter_chunks_for_indexing


def test_filter_chunks_drops_noise_duplicates_and_short_chunks() -> None:
    chunks = [
        {"chunk_id": "c1", "text": "11.4.1 串联电容补偿装置由制造厂成套提供，安装前应进行检查。"},
        {"chunk_id": "c2", "text": "11.4.1 串联电容补偿装置由制造厂成套提供，安装前应进行检查。"},
        {"chunk_id": "c3", "text": "短句"},
        {"chunk_id": "c4", "text": "%PDF-1.7 obj<</Filter/FlateDecode ... endstream"},
    ]

    out, stats = filter_chunks_for_indexing(chunks)
    ids = [x.get("chunk_id") for x in out]
    assert "c1" in ids
    assert "c2" not in ids
    assert "c3" not in ids
    assert "c4" not in ids
    assert stats["dropped_dup"] >= 1
    assert stats["dropped_short"] >= 1
    assert stats["dropped_noise"] >= 1
