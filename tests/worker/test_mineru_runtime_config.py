import sys
import io
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKER_SERVICE = ROOT / "services" / "worker"
if str(WORKER_SERVICE) not in sys.path:
    sys.path.insert(0, str(WORKER_SERVICE))

from worker.mineru_client import MinerUClient


def test_mineru_client_uses_runtime_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    class _DummyResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "pages": [
                    {
                        "page_no": 1,
                        "blocks": [{"type": "paragraph", "text": "runtime mineru"}],
                        "tables": [],
                    }
                ]
            }

    def fake_post(url: str, headers: dict, files: dict, timeout: float):
        captured["url"] = url
        captured["headers"] = headers
        return _DummyResponse()

    monkeypatch.setattr("worker.mineru_client.requests.post", fake_post)

    client = MinerUClient()
    out = client.parse_pdf(
        b"%PDF-1.4",
        runtime_config={
            "mineru_api_base": "https://mineru.example.com",
            "mineru_api_key": "mineru-key",
        },
    )

    assert captured["url"] == "https://mineru.example.com/parse"
    assert captured["headers"]["Authorization"] == "Bearer mineru-key"
    assert out["pages"][0]["blocks"][0]["text"] == "runtime mineru"


def test_mineru_client_supports_mineru_v4_cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {"post_urls": [], "put_urls": [], "get_urls": []}

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("extract/result.md", "# 章节一\n这是云端解析结果")
    zip_payload = zip_buf.getvalue()

    class _Resp:
        status_code = 200

        def __init__(self, payload: dict | None = None, content: bytes = b"", text: str = "") -> None:
            self._payload = payload or {}
            self.content = content
            self.text = text

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    def fake_post(url: str, headers: dict, timeout: float, **kwargs):
        captured["post_urls"].append(url)
        if url.endswith("/file-urls/batch"):
            assert headers["Authorization"] == "Bearer mineru-key"
            assert headers["token"] == "token-1"
            return _Resp(
                payload={
                    "code": 0,
                    "data": {
                        "batch_id": "batch_1",
                        "file_urls": [{"url": "https://upload.example.com/upload.pdf"}],
                    },
                }
            )
        raise AssertionError(f"unexpected post url: {url}")

    def fake_put(url: str, data: bytes, timeout: float, **kwargs):
        captured["put_urls"].append(url)
        assert url == "https://upload.example.com/upload.pdf"
        assert "headers" not in kwargs or not kwargs.get("headers")
        assert data.startswith(b"%PDF")
        return _Resp()

    def fake_get(url: str, timeout: float, **kwargs):
        captured["get_urls"].append(url)
        if url.endswith("/extract-results/batch/batch_1"):
            return _Resp(
                payload={
                    "code": 0,
                    "data": {
                        "extract_result": [
                            {
                                "state": "done",
                                "full_zip_url": "https://download.example.com/result.zip",
                            }
                        ]
                    },
                }
            )
        if url == "https://download.example.com/result.zip":
            return _Resp(content=zip_payload)
        raise AssertionError(f"unexpected get url: {url}")

    monkeypatch.setattr("worker.mineru_client.requests.post", fake_post)
    monkeypatch.setattr("worker.mineru_client.requests.put", fake_put)
    monkeypatch.setattr("worker.mineru_client.requests.get", fake_get)
    monkeypatch.setattr("worker.mineru_client.time.sleep", lambda *_: None)

    client = MinerUClient()
    out = client.parse_pdf(
        b"%PDF-1.4 cloud",
        runtime_config={
            "mineru_api_base": "https://mineru.net/api/v4/extract/task",
            "mineru_api_key": "mineru-key",
            "mineru_token": "token-1",
            "mineru_model_version": "index_pro",
        },
    )

    assert "https://mineru.net/api/v4/file-urls/batch" in captured["post_urls"]
    assert "https://mineru.net/api/v4/extract-results/batch/batch_1" in captured["get_urls"]
    assert out["pages"][0]["blocks"][1]["text"] == "这是云端解析结果"


def test_mineru_client_supports_cloud_file_urls_string_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {"put_urls": []}

    class _Resp:
        status_code = 200

        def __init__(self, payload: dict | None = None, text: str = "") -> None:
            self._payload = payload or {}
            self.text = text
            self.content = text.encode("utf-8")

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    def fake_post(url: str, headers: dict, timeout: float, **kwargs):
        if url.endswith("/file-urls/batch"):
            return _Resp(payload={"success": True, "data": {"batchId": "batch_2", "file_urls": ["https://upload.example.com/u2.pdf"]}})
        if url.endswith("/extract/task/batch"):
            return _Resp(payload={"success": True, "data": {"batchId": "batch_2"}})
        raise AssertionError(f"unexpected post url: {url}")

    def fake_put(url: str, data: bytes, timeout: float, **kwargs):
        captured["put_urls"].append(url)
        assert "headers" not in kwargs or not kwargs.get("headers")
        return _Resp()

    def fake_get(url: str, timeout: float, **kwargs):
        if url.endswith("/extract-results/batch/batch_2"):
            return _Resp(payload={"success": True, "data": {"extract_result": [{"state": "done", "full_md_url": "https://download.example.com/r2.md"}]}})
        if url == "https://download.example.com/r2.md":
            return _Resp(text="# 标题\n内容")
        raise AssertionError(f"unexpected get url: {url}")

    monkeypatch.setattr("worker.mineru_client.requests.post", fake_post)
    monkeypatch.setattr("worker.mineru_client.requests.put", fake_put)
    monkeypatch.setattr("worker.mineru_client.requests.get", fake_get)
    monkeypatch.setattr("worker.mineru_client.time.sleep", lambda *_: None)

    client = MinerUClient()
    out = client.parse_pdf(
        b"%PDF-1.4 cloud",
        runtime_config={"mineru_api_base": "https://mineru.net/api/v4/extract/task", "mineru_api_key": "mineru-key"},
    )

    assert captured["put_urls"] == ["https://upload.example.com/u2.pdf"]
    assert out["pages"][0]["blocks"][1]["text"] == "内容"


def test_mineru_client_strips_bearer_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    class _DummyResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"pages": [{"page_no": 1, "blocks": [{"type": "paragraph", "text": "ok"}], "tables": []}]}

    def fake_post(url: str, headers: dict, files: dict, timeout: float):
        captured["headers"] = headers
        return _DummyResponse()

    monkeypatch.setattr("worker.mineru_client.requests.post", fake_post)
    client = MinerUClient()
    client.parse_pdf(
        b"%PDF-1.4",
        runtime_config={
            "mineru_api_base": "https://mineru.example.com",
            "mineru_api_key": "Bearer abc",
        },
    )
    assert captured["headers"]["Authorization"] == "Bearer abc"


def test_mineru_to_pages_keeps_lines_beyond_400_and_paginates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINERU_TO_PAGES_MAX_LINES", "1000")
    monkeypatch.setenv("MINERU_TO_PAGES_LINES_PER_PAGE", "100")

    text = "\n".join(f"line-{i}" for i in range(1, 601))
    client = MinerUClient()
    out = client._to_pages(text)  # noqa: SLF001

    pages = out.get("pages") or []
    assert len(pages) == 6
    assert pages[0]["page_no"] == 1
    assert pages[-1]["page_no"] == 6

    all_lines = [b.get("text") for p in pages for b in p.get("blocks", [])]
    assert "line-1" in all_lines
    assert "line-600" in all_lines


def test_parse_zip_payload_prefers_structured_json_pages() -> None:
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "extract/result.json",
            '{"pages":[{"page_no":1,"blocks":[{"type":"paragraph","text":"结构化文本"}],"tables":[{"raw_text":"参数表"}],"images":[{"url":"https://img.example.com/1.png","caption":"图1"}]}]}',
        )
        zf.writestr("extract/result.md", "# 标题\\nmd 文本")

    client = MinerUClient()
    out = client._parse_zip_payload(zip_buf.getvalue())  # noqa: SLF001
    pages = out.get("pages") or []
    assert pages[0]["blocks"][0]["text"] == "结构化文本"
    assert pages[0]["tables"][0]["raw_text"] == "参数表"
    assert pages[0]["images"][0]["url"] == "https://img.example.com/1.png"


def test_to_pages_from_structured_json_supports_pdf_info_para_blocks() -> None:
    payload = {
        "pdf_info": [
            {
                "page_idx": 0,
                "para_blocks": [
                    {
                        "type": "title",
                        "lines": [{"spans": [{"type": "text", "content": "第一章 总则"}]}],
                    },
                    {
                        "type": "text",
                        "lines": [{"spans": [{"type": "text", "content": "本规范适用于高压电器施工。"}]}],
                    },
                    {
                        "type": "table",
                        "blocks": [
                            {
                                "type": "table_caption",
                                "lines": [{"spans": [{"type": "text", "content": "表 1 设备参数"}]}],
                            },
                            {
                                "type": "table_body",
                                "lines": [
                                    {
                                        "spans": [
                                            {
                                                "type": "table",
                                                "html": "<table><tr><td>设备</td><td>参数</td></tr><tr><td>断路器</td><td>1250A</td></tr></table>",
                                            }
                                        ]
                                    }
                                ],
                            },
                        ],
                    },
                ],
            }
        ]
    }

    client = MinerUClient()
    out = client._to_pages_from_structured_json(payload)  # noqa: SLF001
    assert out is not None
    page = (out.get("pages") or [])[0]
    assert page["page_no"] == 1
    texts = "\n".join(b.get("text") or "" for b in page.get("blocks", []))
    assert "第一章 总则" in texts
    assert "本规范适用于高压电器施工" in texts
    assert any("设备 参数" in (t.get("raw_text") or "") or "断路器" in (t.get("raw_text") or "") for t in page.get("tables", []))
