import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.build_payload import build_payload  # noqa: E402


class DummyEntityIndex:
    def get_or_create_id(self, kind: str, name: str) -> str:
        return f"{kind[:2]}:{abs(hash(name)) % 10000}"


class TestPayloadBuilder(unittest.TestCase):
    def test_build_payload_has_hybrid_fields(self) -> None:
        chunk = {
            "doc_id": "doc1",
            "version_id": "ver1",
            "doc_name": "demo.pdf",
            "chunk_id": "ck1",
            "chapter_id": "ch1",
            "page_start": 1,
            "page_end": 2,
            "doc_type": "project_proof",
            "text": "张建国任项目经理，110kV，合同金额5000万元",
            "block_ids": ["b_1_1", "b_2_1"],
        }
        ie_assets = [{"data_json": {"voltage_level_kv": 110, "contract_amount_rmb": 50000000}}]
        relations = [
            {
                "type": "PERSON_TO_PROJECT",
                "source_name": "张建国",
                "target_name": "城南变电站",
                "properties": {"role_in_project": "项目经理"},
            }
        ]
        payload = build_payload(chunk, ie_assets, relations, DummyEntityIndex(), "power_param_table")

        self.assertIn("entity_person_ids", payload)
        self.assertIn("rel_person_role", payload)
        self.assertIn("rel_person_role_project", payload)
        self.assertEqual(payload["version_id"], "ver1")
        self.assertEqual(payload["val_voltage_kv"], 110)
        self.assertEqual(payload["val_contract_amount_w"], 5000)
        self.assertEqual(payload["source_type"], "text")

    def test_build_payload_excerpt_strips_table_image_and_html_noise(self) -> None:
        chunk = {
            "doc_id": "doc1",
            "version_id": "ver1",
            "doc_name": "demo.pdf",
            "chunk_id": "ck2",
            "chapter_id": "ch1",
            "page_start": 10,
            "page_end": 10,
            "doc_type": "规范规程",
            "text": "table images/abc123.jpg <table><tr><td>额定电压</td></tr></table> 本标准适用范围为安装交接试验。",
            "block_ids": ["b_10_1"],
        }
        payload = build_payload(chunk, [], [], DummyEntityIndex(), "other")
        excerpt = str(payload.get("excerpt") or "")
        self.assertNotIn("table images/", excerpt)
        self.assertNotIn("<table>", excerpt)
        self.assertIn("本标准适用范围", excerpt)

    def test_build_payload_uses_chunk_clause_id(self) -> None:
        chunk = {
            "doc_id": "doc1",
            "version_id": "ver1",
            "doc_name": "demo.pdf",
            "chunk_id": "ck3",
            "chapter_id": "ch1",
            "page_start": 12,
            "page_end": 12,
            "doc_type": "规范规程",
            "text": "试验电压应符合规定。",
            "clause_id": "3.2.1",
            "source_type": "table_row",
            "table_repr": "row",
            "table_id": "t_12_1",
            "row_index": 2,
            "block_ids": ["b_12_1"],
        }
        payload = build_payload(chunk, [], [], DummyEntityIndex(), "power_param_table")
        self.assertEqual(payload["clause_id"], "3.2.1")
        self.assertEqual(payload["clause_no"], "3.2.1")
        self.assertEqual(payload["source_type"], "table_row")
        self.assertEqual(payload["table_repr"], "row")
        self.assertEqual(payload["table_id"], "t_12_1")
        self.assertEqual(payload["row_index"], 2)

    def test_build_payload_infers_sub_clause_and_mandatory(self) -> None:
        chunk = {
            "doc_id": "doc1",
            "version_id": "ver1",
            "doc_name": "demo.pdf",
            "chunk_id": "ck4",
            "chapter_id": "ch1",
            "page_start": 22,
            "page_end": 22,
            "doc_type": "规范规程",
            "text": "4.12.1(3) 试验时必须将插件拔出。",
            "block_ids": ["b_22_1"],
        }
        payload = build_payload(chunk, [], [], DummyEntityIndex(), "other")
        self.assertEqual(payload["clause_id"], "4.12.1(3)")
        self.assertEqual(payload["clause_no"], "4.12.1(3)")
        self.assertTrue(payload["is_mandatory"])
        self.assertEqual(payload["chapter_no"], "4")
        self.assertEqual(payload["section_no"], "4.12")
        self.assertEqual(payload["article_no"], "4.12.1(3)")
        self.assertEqual(payload["article_path"], ["4", "4.12", "4.12.1"])
        self.assertEqual(payload["constraint_type"], "mandatory")


if __name__ == "__main__":
    unittest.main()
