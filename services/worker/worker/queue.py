"""Queue adapters for worker-side consumption."""

from __future__ import annotations

import json
import os
from typing import Any, Protocol

import redis


class JobQueue(Protocol):
    def pop_document_job(self, timeout_s: int = 5) -> dict[str, Any] | None:
        raise NotImplementedError


class RedisJobQueue:
    def __init__(self, redis_url: str, queue_name: str = "document:process") -> None:
        self.client = redis.Redis.from_url(redis_url, decode_responses=True)
        self.queue_name = queue_name

    def pop_document_job(self, timeout_s: int = 5) -> dict[str, Any] | None:
        item = self.client.brpop(self.queue_name, timeout=timeout_s)
        if not item:
            return None
        _, raw = item
        return json.loads(raw)


class InMemoryJobQueue:
    def __init__(self, jobs: list[dict[str, Any]] | None = None) -> None:
        self.jobs = jobs or []

    def pop_document_job(self, timeout_s: int = 5) -> dict[str, Any] | None:
        if not self.jobs:
            return None
        return self.jobs.pop(0)


def build_job_queue_from_env() -> JobQueue:
    backend = os.getenv("TASK_QUEUE_BACKEND", "auto").lower()
    if backend == "memory":
        return InMemoryJobQueue()

    redis_url = os.getenv("REDIS_URL")
    queue_name = os.getenv("REDIS_QUEUE_NAME", "document:process")
    if redis_url:
        return RedisJobQueue(redis_url=redis_url, queue_name=queue_name)

    return InMemoryJobQueue()
