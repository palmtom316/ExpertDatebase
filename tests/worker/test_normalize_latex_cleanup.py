import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.normalize import _clean_block_text, normalize_result


def test_clean_block_text_strips_latex_command_and_keeps_unit_text() -> None:
    text = r"4.8.4 冷却器持续 30\\mathrm { m i n } 应无渗漏，压力 0.25\\mathrm{M P a}。"
    out = _clean_block_text(text)
    assert r"\mathrm" not in out
    assert "30 min" in out
    assert "0.25 MPa" in out


def test_normalize_result_keeps_clause_block_with_latex_residue() -> None:
    mineru_result = {
        "pages": [
            {
                "page_no": 1,
                "blocks": [
                    {"type": "paragraph", "text": r"4.8.4 冷却器持续 30\mathrm{min} 应无渗漏。"},
                ],
                "tables": [],
            }
        ]
    }
    blocks, tables = normalize_result(mineru_result)
    assert len(blocks) == 1
    assert len(tables) == 0
    assert "4.8.4" in str(blocks[0].get("text") or "")
    assert r"\mathrm" not in str(blocks[0].get("text") or "")
