import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.table_threepack import build_table_threepack


def test_table_threepack() -> None:
    html = "<table><tr><td>A</td><td>B</td></tr><tr><td>1</td><td>2</td></tr></table>"
    chunks = build_table_threepack("DOC", 1, html, "表 1.1 测试表", "tbl_0001")
    assert any(c.payload.get("table_repr") == "summary" for c in chunks)
    assert any(c.payload.get("table_repr") == "row" for c in chunks)
