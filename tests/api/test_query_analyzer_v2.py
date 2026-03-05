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
    clause_filter = next(item for item in must if item["key"] == "clause_no")
    assert "11.4.1" in (clause_filter.get("match") or {}).get("any", [])
    standard_filter = next(item for item in must if item["key"] == "standard_no")
    std_any = (standard_filter.get("match") or {}).get("any", [])
    assert "GB 50147-2010" in std_any or "GB50147-2010" in std_any
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


def test_query_analyzer_v2_extracts_sub_clause_and_mandatory_filter() -> None:
    question = "请给出 4.12.1(3) 强制性条文原文，必须执行"
    filter_json, sparse_query, _ = parse_filter_spec(question, DummyEntityIndex())
    assert filter_json is not None
    must = filter_json["must"]
    clause_filter = next(item for item in must if item["key"] == "clause_no")
    assert "4.12.1(3)" in (clause_filter.get("match") or {}).get("any", [])
    mandatory_filter = next(item for item in must if item["key"] == "is_mandatory")
    assert (mandatory_filter.get("match") or {}).get("value") is True
    assert "4.12.1(3)" in sparse_query
    assert "强制性条文" in sparse_query
