import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.api import admin_docs  # noqa: E402


class _DummyArtifactRepo:
    def __init__(self, storage_key: str) -> None:
        self.storage_key = storage_key

    def get_version_artifacts(self, version_id: str) -> dict:
        return {"version": {"storage_key": self.storage_key}}


class _DummyStorage:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def get_size(self, object_key: str) -> int:
        return len(self.payload)

    def get_bytes(self, object_key: str) -> bytes:
        return self.payload

    def get_range(self, object_key: str, start: int, end: int) -> bytes:
        return self.payload[start : end + 1]


def _install_stubs(monkeypatch, payload: bytes) -> None:
    monkeypatch.setattr("app.api.admin_docs.ARTIFACT_REPO", _DummyArtifactRepo("pdf/demo/source.pdf"))
    monkeypatch.setattr("app.api.admin_docs.OBJECT_STORAGE", _DummyStorage(payload))


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(admin_docs.router)
    return TestClient(app)


def test_source_pdf_get_supports_full_and_range(monkeypatch) -> None:
    payload = b"%PDF-1.7\nabcdefghijklmnopqrstuvwxyz"
    _install_stubs(monkeypatch, payload)
    client = _build_client()

    full = client.get("/api/admin/docs/ver_1/source-pdf")
    assert full.status_code == 200
    assert full.content == payload
    assert full.headers["accept-ranges"] == "bytes"
    assert full.headers["content-type"].startswith("application/pdf")
    assert full.headers["content-length"] == str(len(payload))

    partial = client.get("/api/admin/docs/ver_1/source-pdf", headers={"Range": "bytes=0-7"})
    assert partial.status_code == 206
    assert partial.content == payload[:8]
    assert partial.headers["content-range"] == f"bytes 0-7/{len(payload)}"
    assert partial.headers["content-length"] == "8"

    suffix = client.get("/api/admin/docs/ver_1/source-pdf", headers={"Range": "bytes=-5"})
    assert suffix.status_code == 206
    assert suffix.content == payload[-5:]
    assert suffix.headers["content-range"] == f"bytes {len(payload)-5}-{len(payload)-1}/{len(payload)}"


def test_source_pdf_head_and_invalid_range(monkeypatch) -> None:
    payload = b"%PDF-1.4\n1234567890"
    _install_stubs(monkeypatch, payload)
    client = _build_client()

    head = client.head("/api/admin/docs/ver_2/source-pdf")
    assert head.status_code == 200
    assert head.text == ""
    assert head.headers["accept-ranges"] == "bytes"
    assert head.headers["content-length"] == str(len(payload))

    invalid = client.get("/api/admin/docs/ver_2/source-pdf", headers={"Range": "bytes=999-1000"})
    assert invalid.status_code == 416
    assert invalid.headers["content-range"] == f"bytes */{len(payload)}"
