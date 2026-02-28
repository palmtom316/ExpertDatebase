from pathlib import Path


def test_initial_migration_creates_document_versions() -> None:
    root = Path(__file__).resolve().parents[2]
    migration = root / "services/api-server/alembic/versions/0001_init.py"
    text = migration.read_text(encoding="utf-8")
    assert "document_versions" in text
