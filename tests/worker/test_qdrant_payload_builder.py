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
        self.assertEqual(payload["val_voltage_kv"], 110)
        self.assertEqual(payload["val_contract_amount_w"], 5000)


if __name__ == "__main__":
    unittest.main()
