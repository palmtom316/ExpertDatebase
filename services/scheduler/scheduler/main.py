"""Simple scheduler loop for expiry scan and eval dispatch."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import requests


@dataclass
class SchedulerConfig:
    api_base: str
    expiry_interval_s: int
    eval_interval_s: int


class Scheduler:
    def __init__(self, config: SchedulerConfig) -> None:
        self.config = config
        self._last_expiry = 0.0
        self._last_eval = 0.0

    def _post(self, path: str, payload: dict | None = None) -> None:
        requests.post(
            f"{self.config.api_base}{path}",
            json=payload or {},
            timeout=10,
        )

    def tick(self, now: float | None = None) -> dict[str, bool]:
        ts = now if now is not None else time.time()
        fired = {"expiry_scan": False, "eval_schedule": False}

        if ts - self._last_expiry >= self.config.expiry_interval_s:
            self._post("/api/admin/jobs/cleanup-failed", {"limit": 200})
            self._last_expiry = ts
            fired["expiry_scan"] = True

        if ts - self._last_eval >= self.config.eval_interval_s:
            self._post("/api/admin/eval/runs/start", {"dataset_version": "v1.0"})
            self._last_eval = ts
            fired["eval_schedule"] = True

        return fired


def _build_config() -> SchedulerConfig:
    api_base = os.getenv("SCHEDULER_API_BASE", "http://api-server:8080")
    return SchedulerConfig(
        api_base=api_base.rstrip("/"),
        expiry_interval_s=int(os.getenv("SCHEDULER_EXPIRY_INTERVAL_S", "300")),
        eval_interval_s=int(os.getenv("SCHEDULER_EVAL_INTERVAL_S", "900")),
    )


def run_forever() -> None:
    cfg = _build_config()
    scheduler = Scheduler(cfg)
    print("scheduler started", cfg)
    while True:
        try:
            fired = scheduler.tick()
            if fired["expiry_scan"] or fired["eval_schedule"]:
                print("scheduler tick", fired)
        except Exception as exc:  # noqa: BLE001
            print("scheduler tick failed", str(exc))
        time.sleep(2)


if __name__ == "__main__":
    run_forever()
