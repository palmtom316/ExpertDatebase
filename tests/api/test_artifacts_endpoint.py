import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / 'services' / 'api-server'
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.main import app  # noqa: E402


class TestArtifactsRoute(unittest.TestCase):
    def test_artifacts_route_registered(self) -> None:
        paths = {r.path for r in app.routes}
        self.assertIn('/api/admin/docs/{version_id}/artifacts', paths)
        self.assertIn('/api/admin/docs/{version_id}', paths)


if __name__ == '__main__':
    unittest.main()
