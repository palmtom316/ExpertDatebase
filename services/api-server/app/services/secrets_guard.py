"""Runtime secret guard for production startup."""

from __future__ import annotations

import os
import warnings


_DEFAULT_PATTERNS = [
    "postgres:postgres",
    "redis://redis:6379",
    "minio123",
    "changeme",
    "local-dev-key",
    "changeme_required",
]


def _is_production() -> bool:
    env = os.getenv("APP_ENV", "development").strip().lower()
    return env in {"prod", "production"}


def validate_runtime_secrets() -> None:
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
        if _is_production():
            raise RuntimeError(f"production secrets validation failed for: {', '.join(sorted(hits))}")
        else:
            warnings.warn(
                f"[secrets_guard] Default/placeholder secrets detected for: {', '.join(sorted(hits))}. "
                "This is UNSAFE for production. Set APP_ENV=production to enforce.",
                stacklevel=2,
            )
