import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.table_struct import extract_table_struct


def test_extract_table_struct_uses_vl_fallback_when_confident() -> None:
    tables = [
        {
            "table_id": "t_1_1",
            "page_no": 1,
            "raw_text": "设备参数表",
        }
    ]
    repairs = {
        "t_1_1": {
            "recognized_text": "设备|型号|数量\n断路器|ZW32|2",
            "confidence": 0.9,
        }
    }

    out = extract_table_struct(tables, vl_repairs_by_table_id=repairs)

    assert len(out["device_inventory_table"]) == 1
    item = out["device_inventory_table"][0]
    assert item["repair_strategy"] == "vl_fallback"
    assert item["header"] == ["设备", "型号", "数量"]
    assert item["rows"][0]["cells"] == ["断路器", "ZW32", "2"]


def test_extract_table_struct_falls_back_to_stub_when_low_confidence() -> None:
    tables = [
        {
            "table_id": "t_2_1",
            "page_no": 2,
            "raw_text": "设备参数表",
        }
    ]
    repairs = {
        "t_2_1": {
            "recognized_text": "设备|型号|数量\n主变|SZ11|1",
            "confidence": 0.2,
        }
    }

    out = extract_table_struct(tables, vl_repairs_by_table_id=repairs)

    item = out["device_inventory_table"][0]
    assert item["repair_strategy"] == "stub"
    assert item["rows"]
    assert item["rows"][0]["cells"]


def test_extract_table_struct_keeps_normal_parse_without_fallback() -> None:
    tables = [
        {
            "table_id": "t_3_1",
            "page_no": 3,
            "raw_text": "设备|型号|数量\n主变|SZ11|1",
        }
    ]

    out = extract_table_struct(tables)

    item = out["device_inventory_table"][0]
    assert item["repair_strategy"] == "none"
    assert item["header"] == ["设备", "型号", "数量"]
    assert item["rows"][0]["cells"] == ["主变", "SZ11", "1"]
