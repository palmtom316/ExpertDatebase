"""Shared runtime defaults for OCR, embedding, rerank, and retrieval evaluation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_RETRIEVAL_EVAL_DATASET = (REPO_ROOT / "datasets" / "v1.2" / "retrieval_eval_eight_specs_bid_32.jsonl").resolve()

SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OCR_MODEL = "deepseek-ai/DeepSeek-OCR"
DEFAULT_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-8B"
DEFAULT_RERANK_MODEL = "Qwen/Qwen3-Reranker-8B"
DEFAULT_EMBEDDING_DIMENSIONS = "4096"

_PROVIDER_KEYS = {
    "ocr_provider",
    "llm_provider",
    "embedding_provider",
    "rerank_provider",
    "vl_provider",
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _provider(value: Any) -> str:
    return _clean(value).lower()


def _env(name: str) -> str:
    return _clean(os.getenv(name))


def _env_provider(name: str) -> str:
    provider = _provider(os.getenv(name))
    return "" if provider == "auto" else provider


def _provider_defaults(provider: str, *, default_model: str) -> tuple[str, str]:
    if provider == "openai":
        return OPENAI_BASE_URL, "gpt-4o-mini" if default_model == DEFAULT_OCR_MODEL else default_model
    if provider == "siliconflow":
        return SILICONFLOW_BASE_URL, default_model
    return "", ""


def _coalesce(*values: Any) -> str:
    for value in values:
        text = _clean(value)
        if text:
            return text
    return ""


def apply_runtime_defaults(runtime_config: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(runtime_config or {})
    normalized: dict[str, Any] = {}

    for key, value in raw.items():
        if value is None:
            continue
        text = _provider(value) if key in _PROVIDER_KEYS else _clean(value)
        if text:
            normalized[key] = text
        elif key == "reuse_mineru_artifacts" and isinstance(value, bool):
            normalized[key] = value

    legacy_mineru_base = _clean(raw.get("mineru_api_base"))
    legacy_mineru_key = _coalesce(raw.get("mineru_api_key"), raw.get("mineru_token"))
    if legacy_mineru_base:
        normalized["mineru_api_base"] = legacy_mineru_base
    if legacy_mineru_key:
        normalized["mineru_api_key"] = legacy_mineru_key
    mineru_model_version = _clean(raw.get("mineru_model_version"))
    if mineru_model_version:
        normalized["mineru_model_version"] = mineru_model_version

    ocr_provider = _provider(raw.get("ocr_provider"))
    if not ocr_provider:
        if legacy_mineru_base or legacy_mineru_key:
            ocr_provider = "mineru"
        else:
            ocr_provider = _env_provider("OCR_PROVIDER") or "siliconflow"
    normalized["ocr_provider"] = ocr_provider
    if ocr_provider in {"openai", "siliconflow"}:
        ocr_default_base, ocr_default_model = _provider_defaults(ocr_provider, default_model=DEFAULT_OCR_MODEL)
        normalized["ocr_base_url"] = _coalesce(raw.get("ocr_base_url"), _env("OCR_BASE_URL"), ocr_default_base)
        normalized["ocr_model"] = _coalesce(raw.get("ocr_model"), _env("OCR_MODEL"), ocr_default_model)
    elif "ocr_api_key" in normalized:
        normalized["ocr_api_key"] = _clean(raw.get("ocr_api_key"))

    embedding_provider = _provider(raw.get("embedding_provider")) or _env_provider("EMBEDDING_PROVIDER") or "siliconflow"
    normalized["embedding_provider"] = embedding_provider
    if embedding_provider in {"openai", "siliconflow"}:
        embedding_default_base, embedding_default_model = _provider_defaults(
            embedding_provider,
            default_model=DEFAULT_EMBEDDING_MODEL,
        )
        normalized["embedding_base_url"] = _coalesce(
            raw.get("embedding_base_url"),
            _env("EMBEDDING_BASE_URL"),
            embedding_default_base,
        )
        normalized["embedding_model"] = _coalesce(
            raw.get("embedding_model"),
            _env("EMBEDDING_MODEL"),
            embedding_default_model,
        )
    embedding_dimensions = _coalesce(raw.get("embedding_dimensions"), _env("EMBEDDING_DIMENSIONS"), _env("EMBEDDING_DIM"))
    if not embedding_dimensions and embedding_provider == "siliconflow":
        embedding_dimensions = DEFAULT_EMBEDDING_DIMENSIONS
    if embedding_dimensions:
        normalized["embedding_dimensions"] = embedding_dimensions

    rerank_provider = _provider(raw.get("rerank_provider")) or _env_provider("RERANK_PROVIDER") or "siliconflow"
    normalized["rerank_provider"] = rerank_provider
    if rerank_provider in {"openai", "siliconflow"}:
        rerank_default_base, rerank_default_model = _provider_defaults(rerank_provider, default_model=DEFAULT_RERANK_MODEL)
        normalized["rerank_base_url"] = _coalesce(raw.get("rerank_base_url"), _env("RERANK_BASE_URL"), rerank_default_base)
        normalized["rerank_model"] = _coalesce(raw.get("rerank_model"), _env("RERANK_MODEL"), rerank_default_model)

    return normalized
