import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.ie_extract import extract_assets_from_chapter  # noqa: E402


class TestIEExtractGrounding(unittest.TestCase):
    def test_extract_has_grounding_fields(self) -> None:
        text = """
        项目名称：110kV 城南变电站新建工程
        合同金额：5000万元
        签订日期：2023-06-01
        业主单位：某市电力公司
        """
        assets = extract_assets_from_chapter(text=text, page_no=12)
        self.assertGreater(len(assets), 0)
        item = assets[0]

        # JSON serializable
        json.dumps(item, ensure_ascii=False)

        self.assertIn("source_page", item)
        self.assertIn("source_excerpt", item)
        self.assertIn("source_type", item)
        self.assertEqual(item["source_page"], 12)


if __name__ == "__main__":
    unittest.main()
