import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.main import app  # noqa: E402


def _set_auth_env() -> dict[str, str]:
    old = dict(os.environ)
    os.environ["AUTH_ENABLED"] = "true"
    os.environ["AUTH_TOKENS_JSON"] = '{"admin-token":"system_admin"}'
    return old


def _restore_env(old: dict[str, str]) -> None:
    os.environ.clear()
    os.environ.update(old)


def test_reprocess_keeps_false_reuse_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_reprocess_version(**kwargs):
        captured.update(kwargs)
        return {
            "requeued": True,
            "version_id": "ver_test",
            "doc_id": "doc_test",
            "object_key": "pdf/test.pdf",
            "previous_status": "processed",
        }

    monkeypatch.setattr("app.api.admin_jobs.reprocess_version", fake_reprocess_version)

    old = _set_auth_env()
    try:
        client = TestClient(app)
        res = client.post(
            "/api/admin/jobs/reprocess",
            headers={"Authorization": "Bearer admin-token"},
            json={"version_id": "ver_test", "reuse_mineru_artifacts": False},
        )
        assert res.status_code == 200
        runtime = captured.get("runtime_config") or {}
        assert "reuse_mineru_artifacts" in runtime
        assert runtime["reuse_mineru_artifacts"] is False
    finally:
        _restore_env(old)

