import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.services.doc_registry import JSONDocRegistry, SQLDocRegistry, build_doc_registry_from_env  # noqa: E402


class TestDocRegistryFactory(unittest.TestCase):
    def test_builds_sql_registry_when_db_url_present(self) -> None:
        old = dict(os.environ)
        try:
            os.environ["DATABASE_URL"] = "postgresql://postgres:postgres@localhost:5432/expertkb"
            reg = build_doc_registry_from_env()
            self.assertIsInstance(reg, SQLDocRegistry)
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_builds_json_registry_without_db_url(self) -> None:
        old = dict(os.environ)
        try:
            os.environ.pop("DATABASE_URL", None)
            reg = build_doc_registry_from_env()
            self.assertIsInstance(reg, JSONDocRegistry)
        finally:
            os.environ.clear()
            os.environ.update(old)


if __name__ == "__main__":
    unittest.main()
