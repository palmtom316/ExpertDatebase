import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.normalize import normalize_result


def test_normalize_drops_repeated_header_footer_blocks() -> None:
    mineru_result = {
        "pages": [
            {
                "page_no": 1,
                "blocks": [
                    {"type": "paragraph", "text": "GB 50147-2010 电气装置安装工程 高压电器施工及验收规范"},
                    {"type": "paragraph", "text": "第1页"},
                    {"type": "paragraph", "text": "11.1 一般规定"},
                    {"type": "paragraph", "text": "电容器安装应符合要求。"},
                    {"type": "paragraph", "text": "标准分享网 www.bzfxw.com 免费下载"},
                ],
                "tables": [],
            },
            {
                "page_no": 2,
                "blocks": [
                    {"type": "paragraph", "text": "GB 50147-2010 电气装置安装工程 高压电器施工及验收规范"},
                    {"type": "paragraph", "text": "第2页"},
                    {"type": "paragraph", "text": "11.2 电容器安装"},
                    {"type": "paragraph", "text": "电容器组安装应调配差值。"},
                    {"type": "paragraph", "text": "标准分享网 www.bzfxw.com 免费下载"},
                ],
                "tables": [],
            },
            {
                "page_no": 3,
                "blocks": [
                    {"type": "paragraph", "text": "GB 50147-2010 电气装置安装工程 高压电器施工及验收规范"},
                    {"type": "paragraph", "text": "第3页"},
                    {"type": "paragraph", "text": "11.3 耦合电容器"},
                    {"type": "paragraph", "text": "耦合电容器应按编号安装。"},
                    {"type": "paragraph", "text": "标准分享网 www.bzfxw.com 免费下载"},
                ],
                "tables": [],
            },
        ]
    }

    blocks, _ = normalize_result(mineru_result)
    texts = [b["text"] for b in blocks]
    assert all("标准分享网" not in t for t in texts)
    assert all(not t.startswith("GB 50147-2010") for t in texts)
    assert any("11.2 电容器安装" in t for t in texts)
