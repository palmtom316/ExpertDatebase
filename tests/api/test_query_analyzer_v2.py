import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.services.filter_parser import parse_filter_spec


class DummyEntityIndex:
    def __init__(self) -> None:
        self.ids = {"王磊": "p:2002"}

    def match_names(self, kind: str, question: str) -> list[str]:
        return [name for name in self.ids if name in question]

    def get_id(self, kind: str, name: str) -> str | None:
        return self.ids.get(name)


def test_query_analyzer_v2_extracts_clause_standard_and_certificate() -> None:
    question = "请给我王磊项目经理在110kV项目里，条款11.4.1对应GB 50147-2010和证书号ZJ-A-2024-009的要求"
    filter_json, sparse_query, dense_query = parse_filter_spec(question, DummyEntityIndex())

    assert filter_json is not None
    must = filter_json["must"]
    keys = {item["key"] for item in must}
    assert "entity_person_ids" in keys
    assert "rel_person_role" in keys
    assert "val_voltage_kv" in keys
    assert "clause_no" in keys
    assert "standard_no" in keys
    assert "certificate_no" in keys
    assert "11.4.1" in sparse_query
    assert "GB 50147-2010" in sparse_query
    assert "ZJ-A-2024-009" in sparse_query
    assert dense_query.strip() == question


def test_query_analyzer_v2_handles_amount_in_yi() -> None:
    question = "合同金额2.5亿的项目有哪些"
    filter_json, sparse_query, _ = parse_filter_spec(question, DummyEntityIndex())
    assert filter_json is not None
    amount = next(item for item in filter_json["must"] if item["key"] == "val_contract_amount_w")
    assert amount["range"]["gte"] == 25000
    assert "2.5亿" in sparse_query
