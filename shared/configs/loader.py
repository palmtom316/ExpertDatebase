"""Load versioned YAML/JSON config packs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml


def _base_dir() -> Path:
    return Path(__file__).resolve().parent


def _repair_yaml_double_quoted_backslashes(text: str) -> str:
    # Upstream config contains regex with unescaped backslashes in double quotes.
    # This preserves file content and repairs parsing at load time.
    def repl(match: re.Match[str]) -> str:
        inner = match.group(1)
        return '"' + inner.replace("\\", "\\\\") + '"'

    return re.sub(r'"([^"\n]*\\[^"\n]*)"', repl, text)


def _load_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return yaml.safe_load(_repair_yaml_double_quoted_backslashes(text))


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_all_configs() -> dict[str, dict[str, Any]]:
    base = _base_dir()
    return {
        "keyword_rules": _load_yaml(base / "keyword_rules_v1.yaml"),
        "page_type_rules": _load_yaml(base / "page_type_rules_v1.yaml"),
        "ie_schema": _load_json(base / "ie_schema_v1.json"),
        "table_columns": _load_json(base / "table_columns_v1.json"),
        "routing_policy": _load_json(base / "routing_policy_v1.json"),
    }
