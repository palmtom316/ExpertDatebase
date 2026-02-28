"""Authentication and RBAC helpers."""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import Header, HTTPException, status

ROLE_SYSTEM_ADMIN = "system_admin"
ROLE_BID_ENGINEER = "bid_engineer"
ROLE_EMPLOYEE = "employee"

ALL_ROLES = [ROLE_SYSTEM_ADMIN, ROLE_BID_ENGINEER, ROLE_EMPLOYEE]


def _auth_enabled() -> bool:
    return os.getenv("AUTH_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def _load_token_role_map() -> dict[str, str]:
    raw = os.getenv("AUTH_TOKENS_JSON", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    out: dict[str, str] = {}
    for token, role in parsed.items():
        if not isinstance(token, str) or not isinstance(role, str):
            continue
        out[token.strip()] = role.strip()
    return out


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2:
        return None
    scheme, value = parts
    if scheme.lower() != "bearer":
        return None
    token = value.strip()
    return token or None


def require_roles(allowed_roles: list[str]):
    allowed = set(allowed_roles)

    def dependency(
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> dict[str, Any]:
        if not _auth_enabled():
            return {"role": ROLE_SYSTEM_ADMIN, "auth_mode": "disabled"}

        token = _extract_bearer_token(authorization)
        token_map = _load_token_role_map()
        if not token or token not in token_map:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="unauthorized",
            )

        role = token_map[token]
        if role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="forbidden",
            )
        return {"role": role, "auth_mode": "token"}

    return dependency

