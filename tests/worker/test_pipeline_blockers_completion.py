import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.pipeline import process_mineru_result


def test_pipeline_outputs_quality_classification_and_table_struct() -> None:
    mineru_result = {
        "pages": [
            {
                "page_no": 1,
                "blocks": [
                    {"type": "title", "text": "第一章 项目经理简历"},
                    {
                        "type": "paragraph",
                        "text": "项目名称：城南110kV变电站扩建工程\n项目经理：张建国\n资格证书：一级建造师",
                    },
                ],
                "tables": [
                    {
                        "raw_text": "业绩表\n项目名称|电压等级|金额\n城南站|110kV|5000万元",
                    },
                    {
                        "raw_text": "设备表\n设备|型号|数量\n主变|SZ11|2",
                    },
                    {
                        "raw_text": "资格表\n姓名|证书|编号\n张建国|一级建造师|A123",
                    },
                ],
            }
        ]
    }

    output = process_mineru_result("doc_1", "ver_1", mineru_result)

    assert output["quality_gate"]["grade"] in {"A", "B", "C"}
    assert output["classification"]["doc_type"]
    assert len(output["table_struct"]["power_param_table"]) >= 1
    assert len(output["table_struct"]["device_inventory_table"]) >= 1
    assert len(output["table_struct"]["qualification_table"]) >= 1


def test_pipeline_degrade_strategy_marks_small_chapter_as_degenerate() -> None:
    mineru_result = {
        "pages": [
            {"page_no": 1, "blocks": [{"type": "paragraph", "text": "短文本"}], "tables": []},
            {"page_no": 2, "blocks": [{"type": "paragraph", "text": "再来一点"}], "tables": []},
        ]
    }
    output = process_mineru_result("doc_1", "ver_1", mineru_result)
    assert output["chapters"][0]["status"] == "degenerate"


class _FakeStorage:
    def get_bytes(self, object_key: str) -> bytes:
        return b"pdf-bytes"


def test_entity_index_json_backend_is_stable_across_instances(tmp_path: Path) -> None:
    from worker.entity_index import build_entity_index_from_env

    index_path = tmp_path / "entity-index.json"

    old = dict(os.environ)
    try:
        os.environ["ENTITY_INDEX_BACKEND"] = "json"
        os.environ["ENTITY_INDEX_PATH"] = str(index_path)

        idx1 = build_entity_index_from_env()
        a1 = idx1.get_or_create_id("person", "张建国")

        idx2 = build_entity_index_from_env()
        a2 = idx2.get_or_create_id("person", "张建国")

        assert a1 == a2
        assert a1.startswith("person_")
    finally:
        os.environ.clear()
        os.environ.update(old)
