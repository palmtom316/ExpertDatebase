"""Runtime secret guard for production startup."""

from __future__ import annotations

import os


_DEFAULT_PATTERNS = [
    "postgres:postgres",
    "redis://redis:6379",
    "minio123",
    "changeme",
    "local-dev-key",
]


def _is_production() -> bool:
    env = os.getenv("APP_ENV", "development").strip().lower()
    return env in {"prod", "production"}


def validate_runtime_secrets() -> None:
    if not _is_production():
        return

    checks = {
        "DATABASE_URL": os.getenv("DATABASE_URL", ""),
        "REDIS_URL": os.getenv("REDIS_URL", ""),
        "MINIO_SECRET_KEY": os.getenv("MINIO_SECRET_KEY", ""),
        "AUTH_TOKENS_JSON": os.getenv("AUTH_TOKENS_JSON", ""),
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", ""),
    }

    hits: list[str] = []
    for key, value in checks.items():
        if not value:
            continue
        low = value.lower()
        if any(pattern in low for pattern in _DEFAULT_PATTERNS):
            hits.append(key)

    if hits:
        raise RuntimeError(f"production secrets validation failed for: {', '.join(sorted(hits))}")
