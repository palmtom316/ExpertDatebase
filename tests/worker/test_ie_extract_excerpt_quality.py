import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.ie_extract import extract_assets_from_chapter


def test_ie_excerpt_filters_toc_and_latex_noise() -> None:
    text = """
11.1General requirement …(50) 11.2Installation of capacitor...(52)
4.1.1本章适用于额定电压为 $3 \\mathrm { k V } \\sim 7 5 0 \\mathrm { k V } $
项目名称：城南110kV变电站扩建工程
合同金额：5000万元
业主单位：某电力公司
"""
    assets = extract_assets_from_chapter(text=text, page_no=2)
    assert assets
    excerpt = assets[0].get("source_excerpt") or ""
    assert "项目名称" in excerpt
    assert "合同金额" in excerpt
    assert "\\mathrm" not in excerpt
    assert "11.1General" not in excerpt


def test_ie_excerpt_can_be_empty_when_all_noise() -> None:
    text = "11.1General requirement …(50) 11.2Installation ...(52) $3 \\mathrm{kV}$"
    assets = extract_assets_from_chapter(text=text, page_no=1)
    assert assets == []
