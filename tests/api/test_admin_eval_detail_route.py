import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / 'services' / 'api-server'
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.main import app  # noqa: E402


class TestAdminEvalDetailRoute(unittest.TestCase):
    def test_eval_detail_route_registered(self) -> None:
        paths = {r.path for r in app.routes}
        self.assertIn('/api/admin/eval/results/{result_id}', paths)


if __name__ == '__main__':
    unittest.main()
