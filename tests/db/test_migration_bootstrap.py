from pathlib import Path


def test_initial_migration_creates_document_versions() -> None:
    root = Path(__file__).resolve().parents[2]
    migration = root / "services/api-server/alembic/versions/0001_init.py"
    text = migration.read_text(encoding="utf-8")
    assert "document_versions" in text


def test_second_migration_creates_entity_dictionary() -> None:
    root = Path(__file__).resolve().parents[2]
    migration = root / "services/api-server/alembic/versions/0002_entity_dictionary.py"
    text = migration.read_text(encoding="utf-8")
    assert "entity_dictionary" in text
