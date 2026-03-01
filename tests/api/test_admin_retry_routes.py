import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.main import app  # noqa: E402


class TestAdminRetryRoutes(unittest.TestCase):
    def test_admin_retry_routes_registered(self) -> None:
        paths = {r.path for r in app.routes}
        self.assertIn("/api/admin/jobs/cleanup-failed", paths)
        self.assertIn("/api/admin/jobs/retry-failed", paths)
        self.assertIn("/api/admin/jobs/reprocess", paths)
        self.assertIn("/api/admin/jobs/failed", paths)


if __name__ == "__main__":
    unittest.main()
