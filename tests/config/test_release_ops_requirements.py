import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
API_SERVICE = ROOT / "services" / "api-server"
if str(API_SERVICE) not in sys.path:
    sys.path.insert(0, str(API_SERVICE))

from app.services.secrets_guard import validate_runtime_secrets


def test_production_rejects_default_passwords(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/expertkb")

    with pytest.raises(RuntimeError):
        validate_runtime_secrets()


def test_non_production_allows_default_passwords(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/expertkb")
    validate_runtime_secrets()


def test_compose_includes_scheduler_service() -> None:
    compose = (ROOT / "docker" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "scheduler:" in compose
