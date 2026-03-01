import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.ie.engines.langextract_engine import LangExtractEngine
from worker.ie.grounding.page_offset_mapper import PageOffsetMapper
from worker.ie.validators.power_field_validator import validate_power_fields


def test_langextract_engine_extracts_power_fields_with_offsets() -> None:
    page_text = "项目经理王磊负责110kV线路，合同金额5000万元。"
    mapper = PageOffsetMapper.from_pages([{"page_no": 12, "text": page_text}])
    engine = LangExtractEngine()
    result = engine.extract(page_text, mapper=mapper)
    fields = result["fields"]
    assert fields["voltage_kv"]["value"] == 110
    assert fields["amount_wan"]["value"] == 5000.0
    assert fields["voltage_kv"]["page_no"] == 12
    assert fields["amount_wan"]["page_no"] == 12


def test_power_field_validator_flags_fatal_outlier() -> None:
    errors = validate_power_fields({"voltage_kv": 9999, "amount_wan": 0.001})
    assert any(item["fatal"] for item in errors)
