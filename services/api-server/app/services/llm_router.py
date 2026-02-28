"""LLM routing with commercial provider support and local stub fallback."""

from __future__ import annotations

import os
import time
from typing import Any
from uuid import uuid4

import requests

from app.services.llm_log_repo import LLMLogRepo, build_llm_log_repo_from_env
from shared.configs.loader import load_all_configs


class LLMRouter:
    def __init__(self, log_repo: LLMLogRepo | None = None) -> None:
        self.cfg = load_all_configs().get("routing_policy", {})
        self.log_repo = log_repo or build_llm_log_repo_from_env()
        self.call_logs: list[dict[str, Any]] = []
        self.timeout_s = float(os.getenv("LLM_HTTP_TIMEOUT_S", "30"))

    def _resolve_provider(self, task_type: str) -> tuple[str, str]:
        tiers = self.cfg.get("tasks", {}).get(task_type, ["tier1", "tier2", "tier3"])
        tier_map = self.cfg.get("tiers", {})
        selected_tier = tiers[0] if tiers else "tier1"
        routed_provider = str(tier_map.get(selected_tier, "CN_PRIMARY"))

        configured = os.getenv("LLM_PROVIDER", "auto").strip().lower()
        if configured == "auto":
            if os.getenv("OPENAI_API_KEY"):
                return "openai", routed_provider
            if os.getenv("ANTHROPIC_API_KEY"):
                return "anthropic", routed_provider
            return "stub", routed_provider

        if configured in {"openai", "anthropic", "stub"}:
            return configured, routed_provider

        return "stub", routed_provider

    def _stub_result(self, prompt: str) -> dict[str, Any]:
        response_text = f"根据证据，问题“{prompt}”的答案请参考引用内容。"
        return {
            "text": response_text,
            "provider": "stub",
            "model": "stub-mvp",
            "usage": {"tokens_in": len(prompt), "tokens_out": len(response_text)},
        }

    def _call_openai(self, task_type: str, prompt: str) -> dict[str, Any]:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")

        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        system_prompt = os.getenv(
            "LLM_SYSTEM_PROMPT",
            "You are a factual assistant. Use citations and avoid unsupported claims.",
        )
        temperature = float(os.getenv("OPENAI_TEMPERATURE", "0.2"))

        payload = {
            "model": model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "metadata": {"task_type": task_type},
        }
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()

        text = str((((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")).strip()
        usage = data.get("usage") or {}
        return {
            "text": text or self._stub_result(prompt)["text"],
            "provider": "openai",
            "model": model,
            "usage": {
                "tokens_in": int(usage.get("prompt_tokens", len(prompt))),
                "tokens_out": int(usage.get("completion_tokens", len(text))),
            },
        }

    def _call_anthropic(self, task_type: str, prompt: str) -> dict[str, Any]:
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")

        base_url = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1").rstrip("/")
        model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
        system_prompt = os.getenv(
            "LLM_SYSTEM_PROMPT",
            "You are a factual assistant. Use citations and avoid unsupported claims.",
        )
        max_tokens = int(os.getenv("ANTHROPIC_MAX_TOKENS", "1024"))

        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": prompt}],
            "metadata": {"task_type": task_type},
        }
        resp = requests.post(
            f"{base_url}/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": os.getenv("ANTHROPIC_VERSION", "2023-06-01"),
                "content-type": "application/json",
            },
            json=payload,
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()

        content = data.get("content") or []
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(str(item.get("text", "")))
        text = "\n".join(x for x in text_parts if x).strip()
        usage = data.get("usage") or {}
        return {
            "text": text or self._stub_result(prompt)["text"],
            "provider": "anthropic",
            "model": model,
            "usage": {
                "tokens_in": int(usage.get("input_tokens", len(prompt))),
                "tokens_out": int(usage.get("output_tokens", len(text))),
            },
        }

    def route_and_generate(self, task_type: str, prompt: str) -> dict[str, Any]:
        start = time.time()
        error: str | None = None
        provider, routed_provider = self._resolve_provider(task_type=task_type)

        result: dict[str, Any]
        try:
            if provider == "openai":
                result = self._call_openai(task_type=task_type, prompt=prompt)
            elif provider == "anthropic":
                result = self._call_anthropic(task_type=task_type, prompt=prompt)
            else:
                result = self._stub_result(prompt)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            result = self._stub_result(prompt)

        latency_ms = int((time.time() - start) * 1000)

        log = {
            "id": f"llm_{uuid4().hex[:12]}",
            "request_id": f"req_{uuid4().hex[:12]}",
            "task_type": task_type,
            "provider": result["provider"],
            "model": result["model"],
            "latency_ms": latency_ms,
            "tokens_in": result["usage"]["tokens_in"],
            "tokens_out": result["usage"]["tokens_out"],
            "error": error,
            "metadata_json": {
                "prompt_len": len(prompt),
                "configured_provider": provider,
                "routed_provider": routed_provider,
            },
        }
        self.call_logs.append(log)
        self.log_repo.add_log(log)

        return {
            "text": result["text"],
            "provider": result["provider"],
            "model": result["model"],
            "latency_ms": latency_ms,
            "usage": result["usage"],
        }
