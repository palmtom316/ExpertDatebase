import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.pipeline import process_mineru_result  # noqa: E402


class TestPipelineMVP(unittest.TestCase):
    def test_pipeline_produces_blocks_chapters_chunks(self) -> None:
        mineru_result = {
            "pages": [
                {
                    "page_no": 1,
                    "blocks": [
                        {"type": "title", "text": "第一章 项目概况"},
                        {"type": "paragraph", "text": "这是第一页的正文内容。"},
                    ],
                    "tables": [],
                },
                {
                    "page_no": 2,
                    "blocks": [
                        {"type": "paragraph", "text": "这是第二页正文，包含合同金额5000万元。"}
                    ],
                    "tables": [],
                },
            ]
        }

        output = process_mineru_result("doc_1", "ver_1", mineru_result)
        self.assertGreater(len(output["normalized_blocks"]), 0)
        self.assertGreater(len(output["chapters"]), 0)
        self.assertGreater(len(output["chunks"]), 0)
        self.assertIn("page_start", output["chunks"][0])
        self.assertIn("page_end", output["chunks"][0])


if __name__ == "__main__":
    unittest.main()
