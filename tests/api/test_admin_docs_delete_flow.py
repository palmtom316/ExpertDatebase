import json
import tempfile
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.api.upload import upload_pdf_bytes  # noqa: E402
from app.services.artifact_repo import JSONArtifactRepo  # noqa: E402
from app.services.doc_registry import JSONDocRegistry  # noqa: E402
from app.services.search_service import InMemoryQdrantRepo  # noqa: E402
from app.services.storage import LocalObjectStorage  # noqa: E402


class TestAdminDocsDeleteFlow(unittest.TestCase):
    def test_delete_flow_removes_storage_registry_assets_and_vectors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = LocalObjectStorage(root / "objects")
            registry_path = root / "registry.json"
            registry = JSONDocRegistry(registry_path)
            assets_path = root / "assets.jsonl"
            artifact_repo = JSONArtifactRepo(registry_path=registry_path, assets_path=assets_path)
            qdrant = InMemoryQdrantRepo()

            uploaded = upload_pdf_bytes(
                filename="sample.pdf",
                content=b"%PDF-1.4 mock",
                storage=storage,
                registry=registry,
            )
            version_id = uploaded["version_id"]
            object_key = uploaded["object_key"]
            self.assertTrue(storage.exists(object_key))

            # One matching asset row + one unrelated row.
            assets_path.write_text(
                "\n".join(
                    [
                        json.dumps({"id": "a1", "version_id": version_id, "source_excerpt": "x"}, ensure_ascii=False),
                        json.dumps({"id": "a2", "version_id": "ver_other", "source_excerpt": "y"}, ensure_ascii=False),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            qdrant.upsert(point_id="p1", vector=[0.1], payload={"version_id": version_id, "chunk_text": "a"})
            qdrant.upsert(point_id="p2", vector=[0.2], payload={"version_id": "ver_other", "chunk_text": "b"})

            storage.delete_bytes(object_key)
            removed_assets = artifact_repo.delete_version_assets(version_id=version_id)
            deleted_version = registry.delete_version(version_id=version_id)
            qdrant.delete_by_version(version_id=version_id)

            self.assertIsNotNone(deleted_version)
            self.assertEqual(removed_assets, 1)
            self.assertFalse(storage.exists(object_key))
            self.assertEqual(len(registry.list_versions(limit=100)), 0)
            remaining_assets = assets_path.read_text(encoding="utf-8")
            self.assertNotIn(version_id, remaining_assets)
            self.assertIn("ver_other", remaining_assets)
            self.assertEqual(len(qdrant._records), 1)  # noqa: SLF001
            self.assertEqual(qdrant._records[0]["payload"]["version_id"], "ver_other")  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
