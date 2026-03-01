import tempfile
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.main import app  # noqa: E402
from app.services.doc_registry import JSONDocRegistry  # noqa: E402
from app.services.storage import LocalObjectStorage  # noqa: E402
from app.api.upload import upload_pdf_bytes  # noqa: E402


class TestUploadAPI(unittest.TestCase):
    def test_upload_service_returns_doc_and_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = LocalObjectStorage(Path(tmp) / "objects")
            registry = JSONDocRegistry(Path(tmp) / "registry.json")
            result = upload_pdf_bytes(
                filename="sample.pdf",
                content=b"%PDF-1.4 mock pdf",
                storage=storage,
                registry=registry,
            )

            self.assertIn("doc_id", result)
            self.assertIn("version_id", result)
            self.assertIn("object_key", result)
            self.assertEqual(result.get("doc_type"), "规范规程")

    def test_upload_route_registered(self) -> None:
        paths = {r.path for r in app.routes}
        self.assertIn("/api/upload", paths)


if __name__ == "__main__":
    unittest.main()
