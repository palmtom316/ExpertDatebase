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


def test_filter_keeps_short_scope_clause_with_signal_keywords() -> None:
    chunks = [
        {"chunk_id": "scope_1", "text": "1.0.2 本标准适用范围为电气装置安装工程的交接试验。"},
        {"chunk_id": "def_1", "text": "2.0.1 术语和定义。"},
    ]

    out, stats = filter_chunks_for_indexing(chunks)
    ids = [x.get("chunk_id") for x in out]
    assert "scope_1" in ids
    assert "def_1" in ids
    assert stats["dropped_short"] == 0


def test_filter_drops_noisy_table_row_chunks() -> None:
    chunks = [
        {
            "chunk_id": "tbl_t_9_1_1",
            "source_type": "table_row",
            "text": "参数|数值|备注 | %PDF-1.7 obj<</Filter/FlateDecode ... endstream",
        },
        {
            "chunk_id": "tbl_t_9_1_2",
            "source_type": "cross_page_table_row",
            "text": "参数|数值|备注 | 额定电压|110kV|主变",
        },
    ]

    out, stats = filter_chunks_for_indexing(chunks)
    ids = [x.get("chunk_id") for x in out]
    assert "tbl_t_9_1_1" not in ids
    assert "tbl_t_9_1_2" in ids
    assert stats["dropped_noise"] >= 1


def test_filter_keeps_clause_with_single_latex_residue() -> None:
    chunks = [
        {
            "chunk_id": "c_latex_keep",
            "text": (
                "4.8.4 冷却装置在安装前应按制造厂规定的压力值进行密封试验，"
                "冷却器持续 30\\mathrm{min} 应无渗漏。"
            ),
        }
    ]

    out, stats = filter_chunks_for_indexing(chunks)
    ids = [x.get("chunk_id") for x in out]
    assert "c_latex_keep" in ids
    assert stats["dropped_noise"] == 0


def test_filter_drops_formula_dense_latex_noise() -> None:
    chunks = [
        {
            "chunk_id": "c_latex_noise",
            "text": (
                "\\alpha \\beta \\gamma \\delta \\epsilon "
                "\\mathrm{A} \\mathrm{B} \\mathrm{C} "
                "\\frac{x}{y} \\sqrt{z} \\sum_{i=1}^{n} x_i"
            ),
        },
        {
            "chunk_id": "c_anchor",
            "text": "3.0.6 变压器在安装前应完成交接试验并符合技术文件要求。",
        },
    ]

    out, stats = filter_chunks_for_indexing(chunks)
    ids = [x.get("chunk_id") for x in out]
    assert "c_latex_noise" not in ids
    assert "c_anchor" in ids
    assert stats["dropped_noise"] >= 1
