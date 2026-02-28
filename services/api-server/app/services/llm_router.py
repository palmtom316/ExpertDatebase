"""LLM routing with tier fallback (MVP stub)."""

from __future__ import annotations

import time
from typing import Any

from shared.configs.loader import load_all_configs


class LLMRouter:
    def __init__(self) -> None:
        self.cfg = load_all_configs().get("routing_policy", {})
        self.call_logs: list[dict[str, Any]] = []

    def route_and_generate(self, task_type: str, prompt: str) -> dict[str, Any]:
        tiers = self.cfg.get("tasks", {}).get(task_type, ["tier1", "tier2", "tier3"])
        tier_map = self.cfg.get("tiers", {})

        start = time.time()
        selected_tier = tiers[0] if tiers else "tier1"
        provider = tier_map.get(selected_tier, "CN_PRIMARY")

        response_text = f"根据证据，问题“{prompt}”的答案请参考引用内容。"
        latency_ms = int((time.time() - start) * 1000)

        log = {
            "task_type": task_type,
            "provider": provider,
            "model": f"{provider}-mvp",
            "latency_ms": latency_ms,
            "tokens_in": len(prompt),
            "tokens_out": len(response_text),
            "error": None,
        }
        self.call_logs.append(log)

        return {
            "text": response_text,
            "provider": provider,
            "model": log["model"],
            "latency_ms": latency_ms,
            "usage": {"tokens_in": log["tokens_in"], "tokens_out": log["tokens_out"]},
        }
