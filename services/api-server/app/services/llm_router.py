"""LLM routing with tier fallback, masking, breaker and concurrency controls."""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import requests

from app.services.llm_log_repo import LLMLogRepo, build_llm_log_repo_from_env
from shared.configs.loader import load_all_configs


@dataclass
class _BreakerState:
    fail_count: int = 0
    opened_at: float | None = None


class LLMRouter:
    _global_semaphore: threading.BoundedSemaphore | None = None
    _global_lock = threading.Lock()

    def __init__(self, log_repo: LLMLogRepo | None = None) -> None:
        self.cfg = load_all_configs().get("routing_policy", {})
        self.log_repo = log_repo or build_llm_log_repo_from_env()
        self.call_logs: list[dict[str, Any]] = []
        self.timeout_s = float(os.getenv("LLM_HTTP_TIMEOUT_S", "30"))
        self.max_concurrency = int(os.getenv("LLM_MAX_CONCURRENCY", "3"))
        self.fail_threshold = int(
            os.getenv(
                "LLM_CB_FAIL_THRESHOLD",
                str(((self.cfg.get("circuit_breaker") or {}).get("fail_threshold") or 5)),
            )
        )
        self.cooldown_seconds = int(
            os.getenv(
                "LLM_CB_COOLDOWN_SECONDS",
                str(((self.cfg.get("circuit_breaker") or {}).get("cooldown_seconds") or 300)),
            )
        )
        self._breaker: dict[str, _BreakerState] = {}

        with self._global_lock:
            if self.__class__._global_semaphore is None:
                self.__class__._global_semaphore = threading.BoundedSemaphore(value=max(1, self.max_concurrency))

    def _sanitize_prompt(self, prompt: str) -> str:
        masked = str(prompt)
        masked = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[PHONE]", masked)
        masked = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[EMAIL]", masked)
        masked = re.sub(r"\b\d{17}[\dXx]\b", "[IDCARD]", masked)
        return masked

    def _providers_for_task(self, task_type: str) -> tuple[list[str], dict[str, Any]]:
        configured = os.getenv("LLM_PROVIDER", "auto").strip().lower()
        tier_map = self.cfg.get("tiers", {})
        tiers = self.cfg.get("tasks", {}).get(task_type, ["tier1", "tier2", "tier3"])

        meta: dict[str, Any] = {
            "configured_provider": configured,
            "tiers": tiers,
        }

        if configured in {"openai", "anthropic", "stub"}:
            return [configured], meta

        candidates: list[str] = []
        for tier in tiers:
            tier_name = str(tier_map.get(tier, "")).strip()
            env_key = f"LLM_TIER_PROVIDER_{tier_name}" if tier_name else ""
            mapped = os.getenv(env_key, "").strip().lower() if env_key else ""

            provider = mapped
            if provider not in {"openai", "anthropic", "stub"}:
                if os.getenv("OPENAI_API_KEY"):
                    provider = "openai"
                elif os.getenv("ANTHROPIC_API_KEY"):
                    provider = "anthropic"
                else:
                    provider = "stub"

            if provider not in candidates:
                candidates.append(provider)

        if "stub" not in candidates:
            candidates.append("stub")
        return candidates, meta

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
            raise RuntimeError("OPENAI_API_KEY is required when provider=openai")

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
            raise RuntimeError("ANTHROPIC_API_KEY is required when provider=anthropic")

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

    def _is_breaker_open(self, provider: str) -> bool:
        state = self._breaker.get(provider)
        if not state or state.opened_at is None:
            return False
        if (time.time() - state.opened_at) >= self.cooldown_seconds:
            state.opened_at = None
            state.fail_count = 0
            return False
        return True

    def _record_failure(self, provider: str) -> None:
        state = self._breaker.setdefault(provider, _BreakerState())
        state.fail_count += 1
        if state.fail_count >= self.fail_threshold:
            state.opened_at = time.time()

    def _record_success(self, provider: str) -> None:
        state = self._breaker.setdefault(provider, _BreakerState())
        state.fail_count = 0
        state.opened_at = None

    def _invoke_provider(self, provider: str, task_type: str, prompt: str) -> dict[str, Any]:
        if provider == "openai":
            return self._call_openai(task_type=task_type, prompt=prompt)
        if provider == "anthropic":
            return self._call_anthropic(task_type=task_type, prompt=prompt)
        return self._stub_result(prompt)

    def route_and_generate(self, task_type: str, prompt: str) -> dict[str, Any]:
        start = time.time()
        clean_prompt = self._sanitize_prompt(prompt)
        providers, meta = self._providers_for_task(task_type=task_type)

        attempted: list[str] = []
        errors: list[str] = []
        breaker_open: list[str] = []
        result: dict[str, Any] | None = None

        semaphore = self.__class__._global_semaphore
        assert semaphore is not None

        with semaphore:
            for provider in providers:
                if self._is_breaker_open(provider):
                    breaker_open.append(provider)
                    continue

                attempted.append(provider)
                try:
                    result = self._invoke_provider(provider=provider, task_type=task_type, prompt=clean_prompt)
                    self._record_success(provider)
                    if result.get("provider") != "stub" or provider == "stub":
                        break
                except Exception as exc:  # noqa: BLE001
                    err = str(exc)
                    errors.append(f"{provider}:{err}")
                    self._record_failure(provider)

        if result is None:
            result = self._stub_result(clean_prompt)

        latency_ms = int((time.time() - start) * 1000)
        error = " | ".join(errors) if errors else None

        metadata = {
            "prompt_len": len(clean_prompt),
            "attempted_providers": attempted,
            "errors": errors,
            "circuit_open": breaker_open,
            **meta,
        }

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
            "metadata_json": metadata,
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
