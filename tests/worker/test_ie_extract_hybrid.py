import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.ie_extract import extract_assets_from_chapter


def test_ie_extract_hybrid_merges_custom_and_langextract_fields() -> None:
    text = "项目经理王磊负责110kV线路，合同金额5000万元，执行标准 GB50148-2010。"
    assets = extract_assets_from_chapter(text=text, page_no=6, engine="hybrid")
    assert assets
    project = next((a for a in assets if str(a.get("asset_type") or "") == "project"), None)
    assert project is not None
    data = project.get("data_json") or {}
    assert data.get("voltage_level_kv") == 110
    assert float(data.get("contract_amount_rmb") or 0) >= 5000 * 10000
    assert str(project.get("extract_engine") or "") in {"hybrid", "langextract", "custom"}
    assert str(data.get("extract_engine") or "") == "hybrid"


def test_ie_extract_langextract_falls_back_to_custom_when_no_fields() -> None:
    text = "项目名称：城南变电站\n业主单位：某电力公司"
    assets = extract_assets_from_chapter(text=text, page_no=2, engine="langextract")
    assert assets
    assert any(str(a.get("asset_type") or "") == "project" for a in assets)

