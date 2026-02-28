import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
WORKER_SERVICE = ROOT / "services" / "worker"
for p in [API_SERVICE, WORKER_SERVICE]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from app.services.chat_orchestrator import chat_with_citations  # noqa: E402
from app.services.search_service import InMemoryQdrantRepo  # noqa: E402
from worker.build_payload import build_payload  # noqa: E402
from worker.pipeline import process_mineru_result  # noqa: E402


class DummyEntityIndex:
    def __init__(self) -> None:
        self.store = {}

    def get_or_create_id(self, kind: str, name: str) -> str:
        key = f"{kind}:{name}"
        self.store.setdefault(key, f"{kind[:2]}:{abs(hash(name)) % 10000}")
        return self.store[key]

    def match_names(self, kind: str, question: str) -> list[str]:
        names = []
        for key in self.store:
            _, name = key.split(":", 1)
            if name in question:
                names.append(name)
        return names

    def get_id(self, kind: str, name: str) -> str | None:
        return self.store.get(f"{kind}:{name}")


class TestMVPPipelineToChat(unittest.TestCase):
    def test_end_to_end_minimal_flow(self) -> None:
        mineru_result = {
            "pages": [
                {
                    "page_no": 1,
                    "blocks": [
                        {"type": "title", "text": "第一章 项目概况"},
                        {"type": "paragraph", "text": "张建国担任项目经理，110kV，合同金额5000万元。"},
                    ],
                    "tables": [],
                }
            ]
        }

        pipeline_out = process_mineru_result("doc_1", "ver_1", mineru_result)
        first_chunk = pipeline_out["chunks"][0]
        first_chunk["doc_name"] = "demo.pdf"
        first_chunk["doc_type"] = "project_proof"

        relations = [
            {
                "type": "PERSON_TO_PROJECT",
                "source_name": "张建国",
                "target_name": "城南变电站",
                "properties": {"role_in_project": "项目经理"},
            }
        ]
        ie_assets = [{"data_json": {"voltage_level_kv": 110, "contract_amount_rmb": 50000000}}]
        entity_index = DummyEntityIndex()
        payload = build_payload(first_chunk, ie_assets, relations, entity_index, "power_param_table")

        repo = InMemoryQdrantRepo()
        repo.upsert(point_id=first_chunk["chunk_id"], vector=[0.1, 0.2], payload=payload)

        result = chat_with_citations("张建国项目经理110kV业绩", repo=repo, entity_index=entity_index)

        self.assertIn("answer", result)
        self.assertGreaterEqual(len(result["citations"]), 1)


if __name__ == "__main__":
    unittest.main()
