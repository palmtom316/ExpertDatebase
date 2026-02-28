import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.main import app  # noqa: E402


def _set_auth_env() -> dict[str, str]:
    old = dict(os.environ)
    os.environ["AUTH_ENABLED"] = "true"
    os.environ["AUTH_TOKENS_JSON"] = (
        '{"admin-token":"system_admin","engineer-token":"bid_engineer","employee-token":"employee"}'
    )
    return old


def _restore_env(old: dict[str, str]) -> None:
    os.environ.clear()
    os.environ.update(old)


def test_admin_route_requires_authentication() -> None:
    old = _set_auth_env()
    try:
        client = TestClient(app)
        res = client.get("/api/admin/jobs/failed")
        assert res.status_code == 401
    finally:
        _restore_env(old)


def test_admin_route_forbids_non_admin_role() -> None:
    old = _set_auth_env()
    try:
        client = TestClient(app)
        res = client.get("/api/admin/jobs/failed", headers={"Authorization": "Bearer employee-token"})
        assert res.status_code == 403
    finally:
        _restore_env(old)


def test_admin_route_allows_admin_role() -> None:
    old = _set_auth_env()
    try:
        client = TestClient(app)
        res = client.get("/api/admin/jobs/failed", headers={"Authorization": "Bearer admin-token"})
        assert res.status_code == 200
    finally:
        _restore_env(old)
