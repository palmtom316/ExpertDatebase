import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.vl_enhancer import VLRecognizer, extract_visual_candidates, merge_visual_text_into_mineru


def test_extract_visual_candidates_reads_table_and_image() -> None:
    mineru_result = {
        "pages": [
            {
                "page_no": 1,
                "blocks": [{"type": "image", "text": "设备铭牌", "url": "https://img.example.com/a.png"}],
                "tables": [{"raw_text": "续表 1 主变参数"}],
            }
        ]
    }
    items = extract_visual_candidates(mineru_result)
    kinds = {x["visual_type"] for x in items}
    assert "image" in kinds
    assert "cross_page_table" in kinds


def test_vl_recognizer_fallback_without_key() -> None:
    recognizer = VLRecognizer()
    out = recognizer.enhance(
        candidates=[{"visual_type": "table", "page_no": 1, "text_hint": "参数表"}],
        runtime_config={"vl_provider": "openai", "vl_api_key": ""},
    )
    assert out["enabled"] is False
    assert out["items"][0]["recognized_text"] == "参数表"
    assert out["items"][0]["fallback_reason"] == "provider_disabled_or_missing_key"


def test_vl_recognizer_table_repair_fallback_confidence_shape() -> None:
    recognizer = VLRecognizer()
    out = recognizer.enhance(
        candidates=[{"visual_type": "table", "page_no": 1, "text_hint": "表头|列A\n行1|值1"}],
        runtime_config={"vl_provider": "openai", "vl_api_key": ""},
        task="table_repair",
    )
    item = out["items"][0]
    assert out["task"] == "table_repair"
    assert item["recognized_text"] == "表头|列A 行1|值1"
    assert item["fallback_reason"] == "provider_disabled_or_missing_key"
    assert float(item.get("confidence") or 0.0) == 0.0


def test_merge_visual_text_into_mineru_adds_blocks_and_tables() -> None:
    mineru_result = {"pages": [{"page_no": 1, "blocks": [], "tables": []}]}
    merged = merge_visual_text_into_mineru(
        mineru_result,
        [
            {"visual_type": "image", "page_no": 1, "recognized_text": "一次设备布置图"},
            {"visual_type": "table", "page_no": 1, "recognized_text": "真空断路器额定电流 1250A"},
        ],
    )
    page = merged["pages"][0]
    assert any("VL-image" in (b.get("text") or "") for b in page["blocks"])
    assert any("VL-table" in (b.get("text") or "") for b in page["blocks"])
    assert any("VL-table" in (t.get("raw_text") or "") for t in page["tables"])
